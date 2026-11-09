"""Small Responses API client using the Python standard library."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIError(ValueError):
    pass


def load_env(path):
    """Read only supported settings; never evaluate shell expressions."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, sep, value = line.partition("=")
        if sep and key.strip() in ("OPENAI_API_KEY", "OPENAI_MODEL"):
            value = value.strip()
            if value[:1] in ("'", '"') and value[-1:] == value[:1]:
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].strip()
            os.environ.setdefault(key.strip(), value)


class Client:
    def __init__(self, env_path, max_requests=12):
        load_env(env_path)
        self.key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not self.key:
            raise AIError("Set OPENAI_API_KEY in .env or your environment.")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        self.max_requests = max_requests
        self.requests = 0
        self.tokens = 0

    def respond(self, instructions, inputs, **options):
        if self.requests >= self.max_requests:
            raise AIError("API request budget reached; completed results remain saved.")
        self.requests += 1
        body = {"model": self.model, "instructions": instructions, "input": inputs,
                "store": False, "max_output_tokens": 2500, **options}
        request = Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
                          headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=90) as response:
                result = json.load(response)
        except HTTPError as exc:
            # Do not echo response bodies, headers or credentials into logs.
            try:
                code = json.loads(exc.read()).get("error", {}).get("code")
            except (ValueError, AttributeError, OSError):
                code = None
            finally:
                exc.close()
            if code == "insufficient_quota":
                raise AIError("OpenAI API quota exhausted. Check API project billing and credits before retrying.") from None
            hint = {401: "Check your API key.", 403: "Check project/model permissions.",
                    429: "Check API billing, quota or rate limits."}.get(exc.code, "Check model configuration or try again later.")
            raise AIError(f"OpenAI HTTP {exc.code}. {hint}") from None
        except (URLError, OSError, TimeoutError):
            raise AIError("Could not reach OpenAI. Check your connection; request may have been processed.") from None
        self.tokens += result.get("usage", {}).get("total_tokens", 0)
        if result.get("status") != "completed":
            raise AIError("OpenAI response was incomplete; try a smaller input.")
        return result

    def structured(self, instructions, data, name, schema):
        response = self.respond(instructions, [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
                                text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}})
        try:
            return json.loads(output_text(response))
        except (ValueError, TypeError):
            raise AIError("OpenAI returned no usable structured result (possibly a refusal).") from None


def output_text(response):
    return "\n".join(c["text"] for item in response.get("output", []) if item.get("type") == "message"
                     for c in item.get("content", []) if c.get("type") == "output_text")
