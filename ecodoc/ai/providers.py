"""Провайдеры LLM. Все — на stdlib (urllib), без новых зависимостей.

Контракт один: Provider.chat(system, user) -> str (текст ответа).
Локальные: ollama, lmstudio (и любой OpenAI-совместимый сервер через base_url).
Внешние: anthropic, openai, openrouter, deepseek, gemini, groq, mistral,
xai, together, vsegpt, proxyapi, gigachat, yandexgpt.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.request
import uuid

from ecodoc.ai.config import AIConfig, api_key


class AIError(RuntimeError):
    pass


def _mask(url: str) -> str:
    """Срезать query string из URL для сообщений об ошибках (там могут быть ключи)."""
    return url.split("?", 1)[0]


def _post(url: str, payload: dict, headers: dict, timeout: int = 300,
          insecure: bool = False, ssl_ctx: ssl.SSLContext | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    ctx = ssl_ctx or (ssl._create_unverified_context() if insecure else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AIError(f"{_mask(url)}: HTTP {e.code}: "
                      f"{e.read().decode('utf-8', 'replace')[:500]}")
    except urllib.error.URLError as e:
        raise AIError(f"{_mask(url)}: недоступен ({e.reason})")
    except OSError as e:  # таймауты, обрывы соединения
        raise AIError(f"{_mask(url)}: сетевая ошибка ({e})")
    except json.JSONDecodeError as e:
        raise AIError(f"{_mask(url)}: не-JSON ответ ({e})")


class Provider:
    name = ""

    def __init__(self, cfg: AIConfig):
        self.cfg = cfg
        self.model = cfg.model

    def chat(self, system: str, user: str) -> str:
        raise NotImplementedError


class OllamaProvider(Provider):
    name = "ollama"
    default_url = "http://localhost:11434"

    @property
    def base(self) -> str:
        return (self.cfg.base_url or
                os.environ.get("OLLAMA_HOST_URL", self.default_url)).rstrip("/")

    def chat(self, system: str, user: str) -> str:
        out = _post(f"{self.base}/api/chat", {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 16384},
        }, {})
        return out.get("message", {}).get("content", "")

    def list_models(self) -> list[str]:
        req = urllib.request.Request(f"{self.base}/api/tags")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []


class OpenAICompatProvider(Provider):
    """OpenAI-совместимый /v1/chat/completions — покрывает большинство API."""
    name = "openai"
    base_url = "https://api.openai.com/v1"

    def chat(self, system: str, user: str) -> str:
        key = api_key(self.cfg)
        if not key and self.name not in ("lmstudio",):
            raise AIError(f"{self.name}: не задан API-ключ "
                          f"(переменная окружения, см. `ecodoc ai setup`)")
        base = (self.cfg.base_url or self.base_url).rstrip("/")
        out = _post(f"{base}/chat/completions", {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0,
        }, {"Authorization": f"Bearer {key}"} if key else {})
        return out["choices"][0]["message"]["content"]


def _compat(nm: str, url: str):
    return type(f"{nm.title()}Provider", (OpenAICompatProvider,),
                {"name": nm, "base_url": url})

OpenRouterProvider = _compat("openrouter", "https://openrouter.ai/api/v1")
DeepSeekProvider = _compat("deepseek", "https://api.deepseek.com/v1")
GroqProvider = _compat("groq", "https://api.groq.com/openai/v1")
MistralProvider = _compat("mistral", "https://api.mistral.ai/v1")
XAIProvider = _compat("xai", "https://api.x.ai/v1")
TogetherProvider = _compat("together", "https://api.together.xyz/v1")
VseGPTProvider = _compat("vsegpt", "https://api.vsegpt.ru/v1")
ProxyAPIProvider = _compat("proxyapi", "https://api.proxyapi.ru/openai/v1")
LMStudioProvider = _compat("lmstudio", "http://localhost:1234/v1")


class AnthropicProvider(Provider):
    name = "anthropic"

    def chat(self, system: str, user: str) -> str:
        key = api_key(self.cfg)
        if not key:
            raise AIError("anthropic: не задан ANTHROPIC_API_KEY")
        out = _post("https://api.anthropic.com/v1/messages", {
            "model": self.model or "claude-sonnet-5",
            "max_tokens": 8192,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in out.get("content", []))


class GeminiProvider(Provider):
    name = "gemini"

    def chat(self, system: str, user: str) -> str:
        key = api_key(self.cfg)
        if not key:
            raise AIError("gemini: не задан GEMINI_API_KEY")
        model = self.model or "gemini-2.5-flash"
        # ключ — заголовком, а не в URL: URL попадает в сообщения об ошибках
        out = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent",
            {"systemInstruction": {"parts": [{"text": system}]},
             "contents": [{"role": "user", "parts": [{"text": user}]}],
             "generationConfig": {"temperature": 0}},
            {"x-goog-api-key": key})
        return out["candidates"][0]["content"]["parts"][0]["text"]


class GigaChatProvider(Provider):
    """Сбер GigaChat: OAuth по Authorization key -> Bearer-токен.

    У Сбера сертификаты НУЦ Минцифры («Russian Trusted Root CA»), которых нет
    в стандартном хранилище Python. Отключать проверку TLS для запросов с
    ключом небезопасно, поэтому: либо установите корневой сертификат Минцифры
    (переменная GIGACHAT_CA_BUNDLE = путь к .pem), либо осознанно разрешите
    небезопасный режим (GIGACHAT_INSECURE=1).
    """
    name = "gigachat"

    def _ssl_ctx(self):
        ca = os.environ.get("GIGACHAT_CA_BUNDLE", "")
        if ca:
            return ssl.create_default_context(cafile=ca)
        if os.environ.get("GIGACHAT_INSECURE", "") == "1":
            return ssl._create_unverified_context()
        return None  # системное хранилище; если нет сертификата — ошибка ниже

    def _token(self) -> str:
        auth = api_key(self.cfg)
        if not auth:
            raise AIError("gigachat: не задан GIGACHAT_AUTH_KEY")
        req = urllib.request.Request(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            data=b"scope=GIGACHAT_API_PERS",
            headers={"Authorization": f"Basic {auth}",
                     "RqUID": str(uuid.uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30,
                                        context=self._ssl_ctx()) as r:
                return json.loads(r.read())["access_token"]
        except ssl.SSLError as e:
            raise AIError(
                "gigachat: TLS-сертификат Сбера не прошёл проверку. Установите "
                "корневой сертификат Минцифры (GIGACHAT_CA_BUNDLE=путь к .pem, "
                "скачать: https://www.gosuslugi.ru/crt) или задайте "
                f"GIGACHAT_INSECURE=1 (небезопасно). Детали: {e}")
        except (urllib.error.URLError, OSError, KeyError,
                json.JSONDecodeError) as e:
            raise AIError(f"gigachat oauth: {e}")

    def chat(self, system: str, user: str) -> str:
        out = _post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions", {
            "model": self.model or "GigaChat",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0,
        }, {"Authorization": f"Bearer {self._token()}"}, ssl_ctx=self._ssl_ctx())
        return out["choices"][0]["message"]["content"]


class YandexGPTProvider(Provider):
    name = "yandexgpt"

    def chat(self, system: str, user: str) -> str:
        key = api_key(self.cfg)
        folder = os.environ.get("YANDEX_FOLDER_ID", "")
        if not key or not folder:
            raise AIError("yandexgpt: нужны YANDEX_API_KEY и YANDEX_FOLDER_ID")
        model = self.model or "yandexgpt-lite/latest"
        out = _post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            {"modelUri": f"gpt://{folder}/{model}",
             "completionOptions": {"temperature": 0, "maxTokens": "8000"},
             "messages": [{"role": "system", "text": system},
                          {"role": "user", "text": user}]},
            {"Authorization": f"Api-Key {key}"})
        return out["result"]["alternatives"][0]["message"]["text"]


PROVIDERS: dict[str, type] = {p.name: p for p in (
    OllamaProvider, LMStudioProvider,
    AnthropicProvider, OpenAICompatProvider, OpenRouterProvider,
    DeepSeekProvider, GeminiProvider, GroqProvider, MistralProvider,
    XAIProvider, TogetherProvider, VseGPTProvider, ProxyAPIProvider,
    GigaChatProvider, YandexGPTProvider,
)}


def get_provider(cfg: AIConfig) -> Provider:
    if cfg.provider not in PROVIDERS:
        raise AIError(f"Неизвестный провайдер {cfg.provider!r}. "
                      f"Доступны: {', '.join(sorted(PROVIDERS))}")
    return PROVIDERS[cfg.provider](cfg)


_OLLAMA_MODEL_CACHE: dict = {}


def _ollama_default_model(cfg: AIConfig) -> str:
    """Первая установленная модель Ollama; результат кэшируется на процесс."""
    if "model" in _OLLAMA_MODEL_CACHE:
        return _OLLAMA_MODEL_CACHE["model"]
    try:
        installed = get_provider(AIConfig(**{**cfg.__dict__, "provider": "ollama",
                                             "model": ""})).list_models()
        model = installed[0] if installed else ""
    except Exception:
        model = ""
    _OLLAMA_MODEL_CACHE["model"] = model
    return model


def chat_with_fallback(cfg: AIConfig, system: str, user: str) -> tuple[str, str]:
    """Вернуть (ответ, 'provider/model'); при отказе основного — идём по fallbacks."""
    attempts = [{"provider": cfg.provider, "model": cfg.model}] + list(cfg.fallbacks)
    last_err = None
    # провайдеры, которым обязательно нужна явная модель (иначе 400 «model is required»)
    _need_model = {"ollama", "lmstudio", "openrouter", "deepseek", "groq",
                   "mistral", "together", "vsegpt", "proxyapi", "openai", "xai"}
    for att in attempts:
        prov = att["provider"]
        model = att.get("model", "")
        if not model and prov in _need_model:
            # у ollama автоматически берём первую установленную модель
            # (список кэшируется — иначе HTTP-запрос на каждый анализируемый файл)
            if prov == "ollama":
                model = _ollama_default_model(cfg)
            if not model:
                last_err = AIError(f"{prov}: не задана модель — пропущен")
                continue
        try:
            c = AIConfig(**{**cfg.__dict__, "provider": prov, "model": model})
            text = get_provider(c).chat(system, user)
            return text, f"{prov}/{model}"
        except AIError as e:
            last_err = e
        except (KeyError, IndexError, TypeError) as e:
            # неожиданная форма ответа провайдера — идём к следующему
            last_err = AIError(f"{att['provider']}: неожиданный ответ ({e!r})")
    raise AIError(f"Все провайдеры недоступны. Последняя ошибка: {last_err}")
