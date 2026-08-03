from logic.objects import QuestCompleter, QuestType


class Registrar:
    _QUEST_MAP: dict[QuestType, QuestCompleter] = {}

    @classmethod
    def register(cls, quest_type: QuestType):
        def decorator(func: QuestCompleter) -> QuestCompleter:
            cls._QUEST_MAP[quest_type] = func
            return func
        return decorator

    @classmethod
    def retrive(cls, quest_type: QuestType) -> QuestCompleter:
        if not cls.available(quest_type):
            raise NotImplemented

        return cls._QUEST_MAP[quest_type]

    @classmethod
    def available(cls, quest_type: QuestType) -> bool:
        return quest_type in cls._QUEST_MAP

    @classmethod
    def all(cls) -> list[tuple[QuestType, QuestCompleter]]:
        return list(map(lambda pair: (pair[0], pair[1]), cls._QUEST_MAP.items()))

    def __new__(cls) -> None:
        raise TypeError("Registrar cannot be instantiated")
