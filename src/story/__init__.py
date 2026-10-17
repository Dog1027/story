"""LLM 文字冒險遊戲。"""


def main() -> None:
    from story.ui import StoryApp

    StoryApp().run()
