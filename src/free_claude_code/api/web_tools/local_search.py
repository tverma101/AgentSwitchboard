"""Optional local A3S Search adapter for sandbox metasearch."""

import asyncio
import json
import shutil
from asyncio.subprocess import Process
from urllib.parse import urlparse

from .constants import _MAX_SEARCH_RESULTS

_A3S_BINARY = "a3s-search"
_A3S_ENGINES = "ddg,wiki,bing"
_A3S_TIMEOUT_SECONDS = 8
_A3S_PROCESS_TIMEOUT_SECONDS = 10.0
_A3S_STDOUT_CAP_BYTES = 1_000_000
_A3S_STDERR_CAP_BYTES = 64_000


async def run_local_a3s_search(query: str) -> list[dict[str, str]] | None:
    """Run A3S Search when its local binary is installed."""
    binary = shutil.which(_A3S_BINARY)
    if binary is None:
        return None

    process = await asyncio.create_subprocess_exec(
        binary,
        query,
        "--engines",
        _A3S_ENGINES,
        "--format",
        "json",
        "--limit",
        str(_MAX_SEARCH_RESULTS),
        "--timeout",
        str(_A3S_TIMEOUT_SECONDS),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, _stderr = await asyncio.wait_for(
            _read_process_output(process), timeout=_A3S_PROCESS_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        _terminate_process(process)
        await process.wait()
        raise
    except TimeoutError:
        _terminate_process(process)
        await process.wait()
        raise RuntimeError("local A3S Search timed out") from None

    if len(stdout) > _A3S_STDOUT_CAP_BYTES:
        _terminate_process(process)
        await process.wait()
        raise RuntimeError("local A3S Search output exceeded the safety cap")
    if process.returncode != 0:
        raise RuntimeError(f"local A3S Search exited with code {process.returncode}")

    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("local A3S Search returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("local A3S Search returned a non-object JSON response")

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise RuntimeError("local A3S Search response is missing results")

    results: list[dict[str, str]] = []
    for raw_result in raw_results[:_MAX_SEARCH_RESULTS]:
        if not isinstance(raw_result, dict):
            continue
        url = raw_result.get("url")
        if not isinstance(url, str) or len(url) > 2_048:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue

        title_value = raw_result.get("title")
        title = title_value.strip() if isinstance(title_value, str) else ""
        if not title:
            title = parsed.hostname

        content_value = raw_result.get("content")
        description = content_value.strip() if isinstance(content_value, str) else ""

        result = {"title": title[:1_000], "url": url}
        if description:
            result["description"] = description[:4_000]
        results.append(result)

    return results


async def _read_process_output(process: Process[bytes]) -> tuple[bytes, bytes]:
    """Read bounded child output while continuously draining both pipes."""
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_task = asyncio.create_task(
        _drain_stream_bounded(
            process.stdout,
            _A3S_STDOUT_CAP_BYTES,
            terminate_process=process,
        )
    )
    stderr_task = asyncio.create_task(
        _drain_stream_bounded(process.stderr, _A3S_STDERR_CAP_BYTES)
    )
    try:
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        await process.wait()
        return stdout, stderr
    except BaseException:
        _terminate_process(process)
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        await process.wait()
        raise


async def _drain_stream_bounded(
    stream: asyncio.StreamReader,
    cap_bytes: int,
    *,
    terminate_process: Process[bytes] | None = None,
) -> bytes:
    """Capture at most a bounded prefix while draining the stream to EOF."""
    captured = bytearray()
    capture_limit = cap_bytes + (1 if terminate_process is not None else 0)
    terminated = False
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        if len(captured) < capture_limit:
            remaining = capture_limit - len(captured)
            captured.extend(chunk[:remaining])
        if (
            terminate_process is not None
            and len(captured) > cap_bytes
            and not terminated
        ):
            _terminate_process(terminate_process)
            terminated = True
    return bytes(captured)


def _terminate_process(process: Process[bytes]) -> None:
    """Stop a child whose bounded execution contract has failed."""
    if process.returncode is None:
        process.kill()
