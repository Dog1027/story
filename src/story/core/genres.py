"""題材包：讓喜歡設計故事的人不用改程式，就能加入新的題材。

結構仿照 Agent Skills（Claude Code 的 skill）：每個題材一個資料夾，裡面一份 GENRE.md，
開頭是設定欄位（name、description），後面是給 AI 的寫作指引；可以另外附 premises.md、names.md。

    genres/
    └── 武俠/
        ├── GENRE.md      必要：設定欄位＋寫作指引
        ├── premises.md   選用：「幫我想」用的開頭靈感，一行一個
        └── names.md      選用：人名、地名、組織名的素材，規劃大綱時參考

跟 skill 一樣漸進揭露，用到才載入：
- 目錄（名稱＋描述）：開局規劃大綱時給 AI，請它依前提挑一個題材；玩家也可以自己指定
- 指引（GENRE.md 的內文）：選定後整局放在每回合的提示詞前段（固定不變，不影響快取）
- 附屬檔案：只在特定那次呼叫載入，premises.md 給「幫我想」、names.md 給規劃大綱

題材包放在兩個地方：內建的在 story/genres/（跟著專案），個人的在 ~/.config/story/genres/。名稱相同時個人的優先。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "genres"
PERSONAL_DIR = Path.home() / ".config" / "story" / "genres"
MAX_DESCRIPTION = 200  # 描述的字數上限：目錄每次規劃大綱都會整份送出
MAX_GUIDE = 2000  # 寫作指引的字數上限：每回合都會送出，太長會拖慢、也會稀釋其他規則
MAX_EXTRA = 2000  # premises.md、names.md 的字數上限

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)


@dataclass
class Genre:
    name: str
    description: str
    guide: str  # GENRE.md 的內文：寫作指引
    premises: list[str] = field(default_factory=list)  # premises.md：開頭靈感
    names: str = ""  # names.md：命名素材
    path: Path | None = None


class InvalidGenre(ValueError):
    """題材包格式不對：訊息會說明是哪裡出錯。"""


def parse_genre(folder: Path) -> Genre:
    """讀一個題材資料夾。格式不對時丟出 InvalidGenre。"""
    try:
        text = (folder / "GENRE.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError:
        raise InvalidGenre("找不到 GENRE.md")
    match = FRONTMATTER.match(text)
    if not match:
        raise InvalidGenre("GENRE.md 開頭要有 --- 包起來的設定欄位")
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip().strip("\"'")
    name = fields.get("name") or folder.name
    description = fields.get("description", "")
    guide = match.group(2).strip()
    if not description:
        raise InvalidGenre("缺少 description（AI 靠它判斷故事適不適合這個題材）")
    if len(description) > MAX_DESCRIPTION:
        raise InvalidGenre(f"description 超過 {MAX_DESCRIPTION} 字")
    if not guide:
        raise InvalidGenre("GENRE.md 沒有寫作指引")
    if len(guide) > MAX_GUIDE:
        raise InvalidGenre(f"寫作指引超過 {MAX_GUIDE} 字（目前 {len(guide)} 字）")
    premises = _extra(folder / "premises.md")
    names = _extra(folder / "names.md")
    return Genre(
        name=name,
        description=description,
        guide=guide,
        premises=[line.strip().lstrip("-*").strip() for line in premises.splitlines() if line.strip().lstrip("-*").strip()],
        names=names,
        path=folder,
    )


def _extra(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > MAX_EXTRA:
        raise InvalidGenre(f"{path.name} 超過 {MAX_EXTRA} 字")
    return text


def load_genres(dirs: list[Path] | None = None) -> tuple[dict[str, Genre], list[str]]:
    """讀取所有題材包，回傳 (題材名稱 → 題材, 被略過的題材與原因)。後面的資料夾優先（個人的覆蓋內建的）。"""
    genres: dict[str, Genre] = {}
    problems: list[str] = []
    for root in dirs if dirs is not None else [BUILTIN_DIR, PERSONAL_DIR]:
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                genre = parse_genre(folder)
            except InvalidGenre as e:
                problems.append(f"{folder}：{e}")
                continue
            genres[genre.name] = genre
    return genres, problems
