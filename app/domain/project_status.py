"""Статус проекта нужен, чтобы долгую разработку игры вести видимыми этапами."""

from app.domain.models import ProjectMilestone, ProjectStatus

CURRENT_STATUS = "Ранняя альфа: вертикальный срез с DB-снапшотом, FIFO-партиями, сырьём и операционными объектами"
CURRENT_FOCUS = "Следующий шаг: развивать роли поверх объектов: магазины ритейлера, производственные линии, склады, транспорт и маршруты."

MILESTONES: tuple[ProjectMilestone, ...] = (
    ProjectMilestone(
        title="Вертикальный прототип",
        status="done",
        description="FastAPI, HTML/CSS/JS UI, 5 регионов, 30 FMCG-товаров, демо-симуляция, рейтинги, банки и контракты.",
    ),
    ProjectMilestone(
        title="Сохранение прототипа",
        status="done",
        description="Опциональный JSON-снапшот мира через PROFIT_CHAIN_STATE_FILE, чтобы прототип не терял прогресс при перезапуске.",
    ),
    ProjectMilestone(
        title="Пользователи и владение компаниями",
        status="done",
        description="Регистрация, вход, bearer-токены прототипа и запрет управления чужими защищёнными компаниями.",
    ),
    ProjectMilestone(
        title="Идемпотентное закрытие дня",
        status="done",
        description="Идемпотентный расчёт дня с журналом операций и защитой от двойного закрытия.",
    ),
    ProjectMilestone(
        title="Финансовый контур",
        status="done",
        description="P&L, cash-flow срез, НДС, налог на прибыль, долговая нагрузка и журнал проводок.",
    ),
    ProjectMilestone(
        title="DB-снапшот мира",
        status="done",
        description="SQLAlchemy 2.x async runtime-хранилище полного GameState через PROFIT_CHAIN_DATABASE_URL без утечки строки подключения.",
    ),
    ProjectMilestone(
        title="Партии товаров и срок годности",
        status="done",
        description="InventoryBatch, FIFO, просрочка, качество партий и перенос срока годности по контрактам.",
    ),
    ProjectMilestone(
        title="Сырьё и рецептуры",
        status="done",
        description="Производство ограничено сырьевыми остатками, рецептуры списывают зерно, молоко-сырьё и упаковку.",
    ),
    ProjectMilestone(
        title="Операционные объекты ролей",
        status="done",
        description="Магазин, завод и склад задают дневные мощности и постоянные расходы, а не жёсткие лимиты в коде.",
    ),
    ProjectMilestone(
        title="Расширенные роли",
        status="next",
        description="Магазины ритейлера, производственные линии и сырьё производителя, склады/транспорт/маршруты дистрибьютора.",
    ),
    ProjectMilestone(
        title="Табличное PostgreSQL persistence",
        status="planned",
        description="Миграции и отдельные таблицы домена для компаний, контрактов, кредитов, остатков и отчётов.",
    ),
    ProjectMilestone(
        title="Переговоры и чат",
        status="planned",
        description="Приватные и групповые переговоры, офферы, формирование контрактов из диалога и модерация.",
    ),
    ProjectMilestone(
        title="Финальная альфа",
        status="planned",
        description="Можно играть одному и с друзьями несколько недель рынка без потери прогресса и с понятными отчётами.",
    ),
)


def build_project_status() -> ProjectStatus:
    """Вернуть компактный статус разработки для API и главного экрана."""
    done = sum(1 for milestone in MILESTONES if milestone.status == "done")
    progress = round(done / len(MILESTONES) * 100, 1)
    return ProjectStatus(
        name="Цепочка прибыли",
        status=CURRENT_STATUS,
        current_focus=CURRENT_FOCUS,
        progress_percent=progress,
        milestones=list(MILESTONES),
    )
