"""Schema-bound local Codex invocation; tools and external connections disabled."""
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from jsonschema import validate

async def structured_llm(instruction: str, data: dict, json_schema: dict) -> dict:
    executable = shutil.which("codex")
    if not executable:
        raise ValueError("Codex CLI не установлен; подключите LLM MCP")
    with tempfile.TemporaryDirectory(prefix="tradeguard-language-") as folder:
        schema = Path(folder) / "schema.json"
        output = Path(folder) / "output.json"
        schema.write_text(json.dumps(json_schema), encoding="utf-8")
        command = [executable, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                   "--sandbox", "read-only", "--output-schema", str(schema), "--output-last-message", str(output),
                   "--disable", "shell_tool", "--disable", "apps", "--disable", "plugins",
                   "--disable", "multi_agent", "--disable", "browser_use", "--disable", "computer_use",
                   "--disable", "image_generation", "--disable", "view_image", "--disable", "unified_exec", "--disable", "code_mode_host", "-c", 'web_search="disabled"',
                   "-c", 'approval_policy="never"', "-"]
        environment = {k: v for k, v in os.environ.items() if not any(x in k.upper() for x in ("TINVEST", "INVEST_TOKEN", "API_KEY"))}
        prompt = instruction + "\n" + json.dumps(data, ensure_ascii=False)
        process = await asyncio.create_subprocess_exec(*command, cwd=folder, env=environment,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, stderr = await asyncio.wait_for(process.communicate(prompt.encode("utf-8")), timeout=150)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode or not output.exists():
            raise ValueError("LLM недоступна: проверьте вход Codex CLI. Ответ не подменяется шаблоном.")
        payload = json.loads(output.read_text(encoding="utf-8"))
        validate(payload, json_schema)
        return payload
