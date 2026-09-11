"""Read-only provider checks. Does not generate text, search the web or render video."""

import httpx

from app.services.openrouter import check_response


async def check_providers(settings, transport=None):
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": ok, "detail": detail})

    if settings.is_test:
        add("mode", True, "Offline fixture mode; real providers are not checked")
        return checks

    async with httpx.AsyncClient(timeout=30, follow_redirects=False, transport=transport) as client:
        if settings.llm_provider != "openrouter":
            add("OpenRouter", False, "This check requires LLM_PROVIDER=openrouter")
        elif not settings.llm_api_key.get_secret_value():
            add("OpenRouter key", False, "Set LLM_API_KEY to an OpenRouter API key")
        else:
            try:
                response = await client.get(
                    "https://openrouter.ai/api/v1/key",
                    headers={"Authorization": "Bearer " + settings.llm_api_key.get_secret_value()},
                )
                check_response(response)
                data = response.json()["data"]
                remaining = data.get("limit_remaining")
                usable = not data.get("is_free_tier", False) and (remaining is None or remaining > 0)
                add(
                    "OpenRouter key",
                    usable,
                    "Key accepted; check account balance in OpenRouter"
                    if usable
                    else "Free tier or API key spending limit exhausted; check OpenRouter Credits/Keys",
                )
                response = await client.get("https://openrouter.ai/api/v1/models")
                check_response(response)
                model = next((m for m in response.json()["data"] if m["id"] == settings.llm_model), None)
                params = set(model.get("supported_parameters") or []) if model else set()
                required = {"response_format", "tools", "reasoning"}
                add(
                    "OpenRouter model",
                    bool(model) and required <= params,
                    f"Model {settings.llm_model}: present, required parameters supported"
                    if model and required <= params
                    else "Model missing or required parameters unsupported",
                )
            except Exception as exc:
                # Only our own fixed messages are safe to print.
                from app.errors import PipelineError

                add(
                    "OpenRouter",
                    False,
                    exc.message
                    if isinstance(exc, PipelineError)
                    else "Provider check failed; check network and OpenRouter status",
                )

        if not settings.pexels_api_key.get_secret_value():
            add("Pexels", False, "Set PEXELS_API_KEY")
        else:
            try:
                response = await client.get(
                    "https://api.pexels.com/v1/videos/search",
                    params={"query": "keyboard", "per_page": 1},
                    headers={"Authorization": settings.pexels_api_key.get_secret_value()},
                )
                ok = response.is_success and bool(response.json().get("videos"))
                add(
                    "Pexels",
                    ok,
                    "Key accepted; video search works"
                    if ok
                    else f"No usable response; HTTP {response.status_code}; check key/quota",
                )
            except Exception:
                add("Pexels", False, "Could not verify Pexels; check network and key")
    return checks
