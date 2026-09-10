"""Провайдеры LLM. Все — на stdlib (urllib), без новых зависимостей.

Контракт один: Provider.chat(system, user) -> str (текст ответа).
Локальные: ollama, lmstudio (и любой OpenAI-совместимый сервер через base_url).
Облако через локальную Ollama: ollama_cloud (модели ollama.com).
Внешние: anthropic, openai, openrouter, deepseek, gemini, groq, mistral,
xai, together, vsegpt, proxyapi, gigachat, yandexgpt, cohere, cerebras,
moonshot, zai.
"""
from __future__ import annotations

import contextvars
import json
import os
import ssl
import time
import urllib.request
import uuid
from contextlib import contextmanager

from ecodoc import __version__
from ecodoc.ai.config import AIConfig, _saved_keys, api_key
from ecodoc.ai.registry import is_ollama_cloud


class AIError(RuntimeError):
    pass


def _mask(url: str) -> str:
    """Срезать query string из URL для сообщений об ошибках (там могут быть ключи)."""
    return url.split("?", 1)[0]


# Groq и Cerebras стоят за Cloudflare, который отбивает подпись urllib по
# умолчанию («Python-urllib/3.x») ошибкой 403 «error code: 1010». Это бан по
# подписи клиента, а не по стране: 10.09.2026 тот же запрос по тому же каналу
# с этой подписью давал 403, со своей — 200. Поэтому подпись ставим всегда.
USER_AGENT = f"EcoDoc/{__version__}"

# потолок ожидания ответа для текущего потока: проверка моделей при запуске
# не должна висеть по 5 минут на одной медленной модели
_TIMEOUT_CAP: contextvars.ContextVar = contextvars.ContextVar(
    "ecodoc_ai_timeout_cap", default=None)


@contextmanager
def timeout_cap(seconds: float):
    """Ограничить ожидание каждого запроса к ИИ в этом потоке."""
    token = _TIMEOUT_CAP.set(seconds)
    try:
        yield
    finally:
        _TIMEOUT_CAP.reset(token)


def _post(url: str, payload: dict, headers: dict, timeout: int = 300,
          insecure: bool = False, ssl_ctx: ssl.SSLContext | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                 **headers}, method="POST")
    cap = _TIMEOUT_CAP.get()
    if cap:
        timeout = min(timeout, cap)
    ctx = ssl_ctx or (ssl._create_unverified_context() if insecure else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        # у Mistral модель, не входящая в бесплатный тариф (small/medium/
        # magistral), отвечает обычным 429 — отличает её только заголовок
        # «лимит 0 запросов в минуту» (проверено 10.09.2026 по всем 27 моделям)
        if (e.headers or {}).get("x-ratelimit-limit-req-minute") == "0":
            body += " [лимит тарифа: 0 запросов/мин]"
        raise AIError(f"{_mask(url)}: HTTP {e.code}: {body}")
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
    cloud = False            # облачные ярлыки (…-cloud) — у OllamaCloudProvider

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
        except Exception:
            return []
        # облачные ярлыки лежат в том же списке Ollama, но они НЕ локальные
        return [m["name"] for m in data.get("models", [])
                if is_ollama_cloud(m["name"]) == self.cloud]


class OllamaCloudProvider(OllamaProvider):
    """Облачные модели ollama.com через установленную Ollama.

    Ollama, вошедшая в аккаунт ollama.com (`ollama signin`), отдаёт облачные
    модели (`gpt-oss:120b-cloud`, `nemotron-3-super:cloud` …) тем же /api/chat,
    что и локальные, но считаются они на сервере ollama.com — поэтому это
    отдельный провайдер, а не «Ollama (локально, приватно)»: данные уходят в
    облако. Чтобы модель заработала, её ярлык надо один раз скачать (это
    килобайты) — делаем сами, если Ollama ответила «модель не найдена».
    """
    name = "ollama_cloud"
    cloud = True

    def _pull(self) -> None:
        _post(f"{self.base}/api/pull", {"model": self.model, "stream": False},
              {}, timeout=120)

    def chat(self, system: str, user: str) -> str:
        try:
            return super().chat(system, user)
        except AIError as e:
            if "HTTP 404" not in str(e):
                raise self._explain(e)
        try:                                    # ярлыка нет — скачать и повторить
            self._pull()
            return super().chat(system, user)
        except AIError as e:
            raise self._explain(e)

    @staticmethod
    def _explain(e: AIError) -> AIError:
        low = str(e).lower()
        if any(w in low for w in ("http 401", "unauthorized", "sign in", "signin")):
            return AIError("ollama_cloud: Ollama на этом компьютере не вошла в "
                           f"аккаунт ollama.com — выполните «ollama signin» ({e})")
        return e


class OpenAICompatProvider(Provider):
    """OpenAI-совместимый /v1/chat/completions — покрывает большинство API."""
    name = "openai"
    base_url = "https://api.openai.com/v1"
    extra: dict = {}             # доп. поля запроса у конкретного провайдера

    def _key(self) -> str:
        return api_key(self.cfg)

    def _base(self) -> str:
        return (self.cfg.base_url or self.base_url).rstrip("/")

    def chat(self, system: str, user: str) -> str:
        key = self._key()
        if not key and self.name not in ("lmstudio",):
            raise AIError(f"{self.name}: не задан API-ключ "
                          f"(переменная окружения, см. `ecodoc ai setup`)")
        out = _post(f"{self._base()}/chat/completions", {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0,
            **self.extra,
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
CerebrasProvider = _compat("cerebras", "https://api.cerebras.ai/v1")
MoonshotProvider = _compat("moonshot", "https://api.moonshot.ai/v1")


class ZaiProvider(OpenAICompatProvider):
    """Z.ai (Zhipu) GLM: бесплатные glm-4.7-flash / glm-4.5-flash, из РФ без VPN.

    «Размышления» у GLM включены по умолчанию — выключаем: замер 10.09.2026 на
    извлечении из справки дал 2,7 с вместо 11,4 с при том же результате."""
    name = "zai"
    base_url = "https://api.z.ai/api/paas/v4"
    extra = {"thinking": {"type": "disabled"}}


class CloudflareProvider(OpenAICompatProvider):
    """Cloudflare Workers AI: 10 000 «нейронов» в сутки бесплатно.

    Нужны токен с правами Workers AI и ID аккаунта (он входит в адрес).
    Ключ — либо «ID_аккаунта:токен», либо только токен, а ID отдельно:
    сохранённый `cloudflare_account` или переменная CLOUDFLARE_ACCOUNT_ID."""
    name = "cloudflare"

    def _key(self) -> str:
        raw = api_key(self.cfg)
        acc, sep, token = raw.partition(":")
        if not sep:
            acc, token = "", raw
        self._account = (acc or _saved_keys().get("cloudflare_account", "")
                         or os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
        return token

    def _base(self) -> str:
        if not getattr(self, "_account", ""):
            raise AIError("cloudflare: не задан ID аккаунта (ключ вида "
                          "«ID_аккаунта:токен» или CLOUDFLARE_ACCOUNT_ID)")
        return ("https://api.cloudflare.com/client/v4/accounts/"
                f"{self._account}/ai/v1")


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

    _token_cache: dict = {}     # class-level: {"value": str, "exp": epoch}

    def _token(self) -> str:
        # токен живёт ~30 мин — кэшируем на 25, иначе 2×N HTTP на N чанков
        hit = GigaChatProvider._token_cache
        if hit.get("value") and hit.get("exp", 0) > time.time():
            return hit["value"]
        auth = api_key(self.cfg)
        if not auth:
            raise AIError("gigachat: не задан GIGACHAT_AUTH_KEY")
        req = urllib.request.Request(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            data=b"scope=GIGACHAT_API_PERS",
            headers={"Authorization": f"Basic {auth}",
                     "RqUID": str(uuid.uuid4()),
                     "User-Agent": USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30,
                                        context=self._ssl_ctx()) as r:
                token = json.loads(r.read())["access_token"]
                GigaChatProvider._token_cache = {"value": token,
                                                 "exp": time.time() + 25 * 60}
                return token
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


class CohereProvider(Provider):
    """Cohere Chat API v2 — бесплатный trial-ключ (20 запросов/мин).

    Ключ: dashboard.cohere.com/api-keys → COHERE_API_KEY (или ввод в
    «Сервис → Выбор ИИ», хранится локально в ~/.ecodoc/keys.json).
    """
    name = "cohere"

    def chat(self, system: str, user: str) -> str:
        key = api_key(self.cfg)
        if not key:
            raise AIError("cohere: не задан COHERE_API_KEY "
                          "(бесплатный ключ: dashboard.cohere.com/api-keys)")
        out = _post("https://api.cohere.com/v2/chat", {
            "model": self.model or "command-a-03-2025",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0,
        }, {"Authorization": f"Bearer {key}"})
        msg = out.get("message", {})
        return "".join(c.get("text", "") for c in msg.get("content", []))


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
    GigaChatProvider, YandexGPTProvider, CohereProvider, CerebrasProvider,
    MoonshotProvider, OllamaCloudProvider, ZaiProvider, CloudflareProvider,
)}


def get_provider(cfg: AIConfig) -> Provider:
    if cfg.provider not in PROVIDERS:
        raise AIError(f"Неизвестный провайдер {cfg.provider!r}. "
                      f"Доступны: {', '.join(sorted(PROVIDERS))}")
    return PROVIDERS[cfg.provider](cfg)


_OLLAMA_MODEL_CACHE: dict = {}

# «остывание» провайдера: после сетевого сбоя не долбим его каждый чанк
# (иначе N файлов × таймаут). Ключ — provider, значение — epoch, до которого
# провайдер пропускается. Ошибки формата/ключа не кулдаунят (могут быть
# специфичны для одного запроса).
_COOLDOWN: dict = {}
_COOLDOWN_SEC = 300
_LOCAL_PROVIDERS = {"ollama", "lmstudio"}
_RATE_WAIT = 6      # пауза при HTTP 429 (лимит запросов в минуту) перед повтором


def _cooling(provider: str) -> bool:
    return _COOLDOWN.get(provider, 0) > time.time()


def _mark_dead(provider: str, err: Exception) -> None:
    text = str(err).lower()
    conn = any(w in text for w in ("недоступ", "connection", "unreachable",
                                   "refused", "getaddrinfo"))
    slow = "timeout" in text or "timed out" in text
    # неверный/заблокированный ключ (401/403) — это не временный сбой:
    # выключаем провайдера надолго, иначе он тормозит КАЖДЫЙ документ
    if "http 401" in text or "http 403" in text:
        _COOLDOWN[provider] = time.time() + 3600
        return
    if provider in _LOCAL_PROVIDERS:
        # локальный сервер: таймаут = модель долго жуёт большой документ,
        # а не «сервер умер» — не пропускаем из-за этого остальные файлы;
        # остывание (короткое) только при явном отказе соединения
        if conn and not slow:
            _COOLDOWN[provider] = time.time() + 60
    elif conn or slow:
        _COOLDOWN[provider] = time.time() + _COOLDOWN_SEC


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
        if _cooling(prov):
            last_err = AIError(f"{prov}: пропущен после недавнего сбоя "
                               "(файл остаётся в приёме — повторите анализ позже)")
            continue
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
            try:
                text = get_provider(c).chat(system, user)
            except AIError as e:
                # 429 = упёрлись в лимит запросов в минуту (бесплатные ключи:
                # у Cohere 20/мин). Ждём и пробуем ЭТОТ же провайдер ещё раз —
                # уходить на запасной из-за секундной паузы незачем.
                if "429" not in str(e) and "rate limit" not in str(e).lower():
                    raise
                time.sleep(_RATE_WAIT)
                text = get_provider(c).chat(system, user)
            return text, f"{prov}/{model}"
        except AIError as e:
            last_err = e
            _mark_dead(prov, e)   # сетевой сбой → «остывание», не долбим каждый чанк
        except (KeyError, IndexError, TypeError) as e:
            # неожиданная форма ответа провайдера — идём к следующему
            last_err = AIError(f"{att['provider']}: неожиданный ответ ({e!r})")
    raise AIError(f"Все провайдеры недоступны. Последняя ошибка: {last_err}")
