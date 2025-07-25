from .computer_skill import ComputerSkill
from .csv_reader_skill import CSVReaderSkill
from .jinja_render_skill import JinjaRenderSkill
from .json_merge_skill import JSONMergeSkill
from .markdown_to_html_skill import MarkdownToHTMLSkill
from .sleep_skill import SleepSkill
from .sum_skill import SumSkill
from .summarizer_skill import SummarizerSkill

try:
    from ..registry import global_skill_registry

    global_skill_registry.register("json_merge", JSONMergeSkill())
    global_skill_registry.register("sleep", SleepSkill())
    global_skill_registry.register("sum", SumSkill())
    global_skill_registry.register("computer", ComputerSkill())
    global_skill_registry.register("markdown_to_html", MarkdownToHTMLSkill())
    global_skill_registry.register("jinja_render", JinjaRenderSkill())
    global_skill_registry.register("csv_reader", CSVReaderSkill())
    global_skill_registry.register("summarizer", SummarizerSkill())
    from .rows_validator_skill import RowsValidatorSkill

    global_skill_registry.register("rows_validator", RowsValidatorSkill())
    from .insights_skill import InsightsSkill

    global_skill_registry.register("insights", InsightsSkill())
    from .line_item_generator_skill import LineItemGeneratorSkill

    global_skill_registry.register("line_item_generator", LineItemGeneratorSkill())

    from .csv_writer_skill import CSVWriterSkill

    global_skill_registry.register("csv_writer", CSVWriterSkill())
except Exception:  # pragma: no cover
    pass
