"""Ejecuta comandos del sistema sin shell (siempre con lista de argumentos)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, Sequence


class CommandNotFound(Exception):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


class CommandRunner(Protocol):
    async def __call__(self, args: Sequence[str], timeout: float = 5.0) -> CommandResult: ...


async def run_command(args: Sequence[str], timeout: float = 5.0) -> CommandResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise CommandNotFound(args[0]) from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return CommandResult(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))
