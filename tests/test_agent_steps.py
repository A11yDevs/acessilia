"""Tests for ReaderAgent and EditorAgent enveloped as Agno step functions."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

from backend.agents.editor_agent import EditorAgent, editor_step
from backend.agents.reader_agent import ReaderAgent, reader_step
from backend.agents.types import RegionTask


def test_reader_agent_step_dict_input(tmp_path: Path):
    sample_file = tmp_path / "page.png"
    sample_file.write_bytes(b"fake image data")

    agent = ReaderAgent()
    mock_tasks = [
        RegionTask(
            agent_target="editor",
            classification="text_clean",
            text="Heading 1",
            page_num=1,
        )
    ]

    with patch.object(agent, "analyse_page", return_value=mock_tasks) as mock_analyse:
        step_input = StepInput(input={"page_path": str(sample_file), "page_num": 2, "total_pages": 5})
        output = agent.execute_step(step_input)

        assert isinstance(output, StepOutput)
        assert output.success is True
        assert output.content["page_num"] == 2
        assert output.content["total_pages"] == 5
        assert output.content["tasks"] == mock_tasks
        assert output.content["total_tasks"] == 1
        mock_analyse.assert_called_once_with(
            page_path=sample_file,
            page_num=2,
            total_pages=5,
            is_pdf=False,
        )


def test_reader_agent_step_path_input(tmp_path: Path):
    sample_file = tmp_path / "document.pdf"
    sample_file.write_bytes(b"%PDF-1.4 fake")

    agent = ReaderAgent()
    with patch.object(agent, "analyse_page", return_value=[]) as mock_analyse:
        step_input = StepInput(input=str(sample_file))
        output = agent(step_input)  # testing __call__

        assert output.success is True
        assert output.content["is_pdf"] is True
        mock_analyse.assert_called_once_with(
            page_path=sample_file,
            page_num=1,
            total_pages=1,
            is_pdf=True,
        )


def test_reader_agent_step_missing_input():
    agent = ReaderAgent()
    step_input = StepInput(input={})
    output = agent.execute_step(step_input)

    assert output.success is False
    assert "ReaderAgent requires" in output.error


def test_reader_agent_as_step_and_module_func():
    agent = ReaderAgent()
    step_obj = agent.as_step()
    assert isinstance(step_obj, Step)
    assert step_obj.name == "ReaderAgent"

    step_input = StepInput(input={})
    output = reader_step(step_input)
    assert output.success is False


def test_editor_agent_step_direct_input():
    agent = EditorAgent()
    tasks = [
        RegionTask(
            agent_target="editor",
            classification="text_clean",
            text="Direct text content",
            page_num=1,
        )
    ]
    step_input = StepInput(input={"tasks": tasks, "results": {}})
    output = agent.execute_step(step_input)

    assert isinstance(output, StepOutput)
    assert output.success is True
    assert output.content == "Direct text content"


def test_editor_agent_step_from_previous_step_content():
    agent = EditorAgent()
    tasks = [
        RegionTask(
            agent_target="editor",
            classification="text_clean",
            text="Chained text content",
            page_num=1,
        )
    ]
    step_input = StepInput(
        input=None,
        previous_step_content={"tasks": tasks, "results": {}},
    )
    output = agent(step_input)  # testing __call__

    assert output.success is True
    assert output.content == "Chained text content"


def test_editor_agent_step_missing_tasks():
    agent = EditorAgent()
    step_input = StepInput(input={})
    output = agent.execute_step(step_input)

    assert output.success is False
    assert "no tasks" in output.error


def test_editor_agent_as_step_and_module_func():
    agent = EditorAgent()
    step_obj = agent.as_step()
    assert isinstance(step_obj, Step)
    assert step_obj.name == "EditorAgent"

    step_input = StepInput(input={})
    output = editor_step(step_input)
    assert output.success is False


def test_reader_and_editor_in_agno_workflow(tmp_path: Path):
    sample_file = tmp_path / "page_1.png"
    sample_file.write_bytes(b"data")

    reader = ReaderAgent()
    editor = EditorAgent()

    mock_tasks = [
        RegionTask(
            agent_target="editor",
            classification="text_clean",
            text="Accessible Page Header",
            page_num=1,
        ),
        RegionTask(
            agent_target="editor",
            classification="text_clean",
            text="Accessible Page Body Paragraph.",
            page_num=1,
        ),
    ]

    with patch.object(reader, "analyse_page", return_value=mock_tasks):
        wf = Workflow(name="accessible_page_pipeline", steps=[reader, editor])
        result = wf.run(input={"page_path": str(sample_file), "page_num": 1})

        assert result is not None
        assert "Accessible Page Header" in result.content
        assert "Accessible Page Body Paragraph." in result.content
