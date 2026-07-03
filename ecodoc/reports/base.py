"""Контракт формы отчётности.

Любая форма проходит один и тот же путь:
    context (данные) -> validate() -> render_xml() + render_print()

Конкретные формы наследуют Report и реализуют три метода. Общий жизненный
цикл (валидация перед выгрузкой, создание каталога) живёт здесь.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ecodoc.core.models import Issue, ReportContext


class Report(ABC):
    code: str = ""           # машинный код формы (для CLI)
    title: str = ""          # человекочитаемое название
    domain: str = "reporting"  # контур: reporting (Отчётность) | development (Разработка)
    implemented: bool = True # False => каркас, выгрузка заблокирована
    has_xml: bool = True     # форма выгружается в XML (для ЛКПП)
    has_print: bool = True   # форма имеет печатную/документную версию

    def __init__(self, context: ReportContext):
        self.ctx = context

    # --- обязательные методы формы ---
    @abstractmethod
    def validate(self) -> list[Issue]:
        """Проверить данные. Вернуть список ошибок/предупреждений."""

    @abstractmethod
    def render_xml(self, out_path: Path) -> Path:
        """Сгенерировать XML для загрузки в ЛКПП/Модуль природопользователя."""

    @abstractmethod
    def render_print(self, out_path: Path) -> Path:
        """Сгенерировать печатную форму (Excel или Word)."""

    # --- общий хелпер ---
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.validate())

    @staticmethod
    def _ensure_dir(path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class NotImplementedReport(Report):
    """База для зарегистрированных, но ещё не реализованных форм (каркас)."""
    implemented = False

    def validate(self) -> list[Issue]:
        return [Issue("error", "форма",
                      f"Форма «{self.title}» пока не реализована (каркас). "
                      f"Модель данных готова — нужен генератор XML/печати.")]

    def render_xml(self, out_path: Path) -> Path:
        raise NotImplementedError(self.title)

    def render_print(self, out_path: Path) -> Path:
        raise NotImplementedError(self.title)
