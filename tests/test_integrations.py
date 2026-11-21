"""Integrations with mainstream libraries, each skipped when its extra is not installed (CI's "all extras" job runs
them all). Nothing here needs an account, a network or Docker: MLflow writes to a folder, W&B runs offline, Langfuse
and OpenTelemetry export to memory."""
import json
import time

import pytest
from conftest import write_finished_run

import llmdyno

T0 = time.time() - 300


@pytest.fixture(scope="module")
def results():
    """A real finished run (with transcript and proxy log) plus the bundled sample, as one Results."""
    prof = llmdyno.cloud_model("custom", "int-model", base_url="http://localhost:9/integrations/v1", pricing=None,
                               name="Integration profile")
    write_finished_run("plan_int", "run_int_1", prof.id, T0)
    was = llmdyno.sample_status()["loaded"]
    sample = llmdyno.load_sample()
    yield llmdyno.results(["plan_int", sample])
    llmdyno.plan("plan_int").delete()
    prof.delete()
    if not was:
        llmdyno.unload_sample()


def test_missing_extra_says_what_to_install(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_polars(name, *a, **k):
        if name == "polars":
            raise ImportError("no polars")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_polars)
    from llmdyno.integrations import require
    with pytest.raises(llmdyno.LLMDynoError, match=r'pip install "llmdyno\[data\]"'):
        require("polars", "data", "to_polars()")


# ------------------------------------------------------------------ data
def test_frames_and_parquet(results, tmp_path):
    pd = pytest.importorskip("pandas")
    assert len(results.to_pandas()) == 16 and "final" in results.to_pandas().columns
    cells = results.to_pandas("cells")
    assert isinstance(cells, pd.DataFrame) and {"benchmark_id", "pass_rate"} <= set(cells.columns)
    assert len(results.to_pandas("reviews")) == 150
    with pytest.raises(ValueError):
        results.rows("nope")
    pl = pytest.importorskip("polars")
    runs = results.to_polars("runs")
    assert isinstance(runs, pl.DataFrame) and runs.height == 76
    pq = pytest.importorskip("pyarrow.parquet")
    path = results.to_parquet(tmp_path / "runs.parquet")
    assert pq.read_table(path).num_rows == 76
    t = llmdyno.run("run_int_1").transcript()
    assert list(t.to_polars()["finish"]) == ["tool_calls", "stop"] and t.to_pandas()["tokens_input"].sum() == 250


# ------------------------------------------------------------------ charts
@pytest.mark.parametrize("backend", ["matplotlib", "plotly"])
def test_every_chart(results, backend):
    if backend == "matplotlib":
        mpl = pytest.importorskip("matplotlib")
        mpl.use("Agg")
    else:
        pytest.importorskip("plotly")
    p = results.plot
    for fig in (p.leaderboard(backend=backend), p.heatmap("correctness", backend=backend),
                p.pareto(x="wall_s_total", backend=backend), p.radar(backend=backend), p.tokens(backend=backend)):
        assert fig is not None
    if backend == "matplotlib":
        import matplotlib.pyplot as plt
        fig = p.leaderboard()
        labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
        best = results.best()
        assert labels[-1] == f"{best['profile']} · {best['harness']}"     # best on top, as in the dashboard
        plt.close("all")
    else:
        fig = p.leaderboard(backend="plotly")
        assert [tr.name for tr in fig.data] == ["Correctness", "Instruction following", "Code quality", "Efficiency"]


# ------------------------------------------------------------------ notebooks
def test_html_reprs_and_live_panel(results):
    assert "llmdyno-bar" in results._repr_html_()
    plan = llmdyno.plan("plan_int")
    assert "Test plan plan_int" in plan._repr_html_() and "t0_smoke_cli" in plan._repr_html_()
    assert "Correctness" in llmdyno.run("run_int_1")._repr_html_()
    pytest.importorskip("ipywidgets")
    panel = plan.live()
    panel._thread.join(timeout=20)
    assert panel.bar.value == 1 and "done" in panel.status.value and "t0_smoke_cli" in panel.table.value
    pytest.importorskip("tqdm")
    from llmdyno.integrations.notebook import progress_bar
    bar = progress_bar(3, "x")
    bar.update(1)
    assert bar.n == 1
    bar.close()


# ------------------------------------------------------------------ tracking and tracing
def test_mlflow(results, tmp_path, monkeypatch):
    pytest.importorskip("mlflow")
    import mlflow
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")      # MLflow 3 keeps the folder store for local use only
    uri = (tmp_path / "mlruns").as_uri()
    ids = results.log_to_mlflow(experiment="llmdyno-test", tracking_uri=uri)
    assert len(ids) == 16
    client = mlflow.tracking.MlflowClient(tracking_uri=uri)
    ours = [client.get_run(i) for i in ids if client.get_run(i).data.params.get("profile") == "Integration profile"][0]
    assert ours.data.metrics["correctness"] == 100.0 and ours.data.params["harness_id"] == "pi"
    assert ours.data.tags["llmdyno.plans"] == "plan_int,plan_sample_round1"
    arts = [a.path for a in client.list_artifacts(ours.info.run_id, "transcripts")]
    assert arts == ["transcripts/t0_smoke_cli-1-run_int_1.jsonl"]


def test_wandb_offline(results, tmp_path, monkeypatch):
    pytest.importorskip("wandb")
    monkeypatch.setenv("WANDB_SILENT", "true")
    run_id = results.log_to_wandb(project="llmdyno-test", mode="offline", dir=str(tmp_path))
    runs = list((tmp_path / "wandb").glob(f"offline-run-*-{run_id}"))
    assert runs and any(runs[0].rglob("*.wandb"))


def test_otel_spans(results):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    n = results.to_otel(tracer_provider=provider)
    spans = exporter.get_finished_spans()
    assert n == len(spans) == 76 + 2                       # one per run, plus the real run's two model requests
    chats = [s for s in spans if s.name.startswith("chat")]
    assert [s.attributes["gen_ai.usage.input_tokens"] for s in chats] == [100, 150]
    assert chats[0].start_time == int(T0 * 1e9) and chats[0].parent.span_id == next(
        s for s in spans if s.attributes.get("llmdyno.run_id") == "run_int_1").context.span_id


def test_langfuse_with_the_real_client(results):
    pytest.importorskip("langfuse")
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    client = Langfuse(public_key="pk-lf-test", secret_key="sk-lf-test", host="http://127.0.0.1:9",
                      tracer_provider=provider)
    only = llmdyno.results("plan_int")
    ids = only.log_to_langfuse(client=client)
    assert len(ids) == 1
    spans = exporter.get_finished_spans()
    gens = [s for s in spans if s.attributes.get("langfuse.observation.type") == "generation"]
    assert len(gens) == 2
    usage = json.loads(gens[0].attributes["langfuse.observation.usage_details"])
    assert usage["input"] == 100 and usage["output"] == 20


def test_auto_log_dispatch(results):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from llmdyno.integrations.tracking import auto_log
    out = auto_log(llmdyno.results("plan_int"), {"otel": {"tracer_provider": TracerProvider()}})
    assert out == {"otel": 3}
    with pytest.raises(llmdyno.LLMDynoError, match="auto_log knows"):
        auto_log(results, "nope")


# ------------------------------------------------------------------ Inspect AI
def test_inspect_task_samples_and_log(results, tmp_path, monkeypatch):
    pytest.importorskip("inspect_ai")
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.log import read_eval_log

    from llmdyno import lib
    real = llmdyno.results("plan_int")
    monkeypatch.setattr(lib, "bench", lambda *a, **k: real)        # the run itself is covered elsewhere
    task = llmdyno.inspect_task(["t0_smoke_cli"], "Integration profile")
    logs = inspect_eval(task, model="none/none", log_dir=str(tmp_path / "logs"), display="none")
    assert logs[0].status == "success"
    assert logs[0].results.scores[0].metrics["mean"].value == 1.0
    assert logs[0].samples[0].output.completion == "Done: hello.py prints hi."

    suite = llmdyno.import_inspect_samples(
        [Sample(input="What is 2 + 2?", target="4", id="q1"),
         Sample(input="Which colour is the sky?", choices=["red", "blue"], target="B", id="q2")], prefix="sdkinspect")
    try:
        assert suite.benchmark_ids == ["sdkinspect_q1", "sdkinspect_q2"]
        spec = llmdyno.benchmark("sdkinspect_q2").spec()
        assert "B. blue" in spec["stages"][0]["prompt"] and "answer.txt" in spec["stages"][0]["prompt"]
        assert spec["checks"][0] == {"name": "answer", "type": "file_contains", "path": "answer.txt", "text": "B"}
    finally:
        suite.delete()
        for bid in ("sdkinspect_q1", "sdkinspect_q2"):
            llmdyno.benchmark(bid).delete()

    path = results.to_inspect_log(tmp_path / "llmdyno.eval")
    log = read_eval_log(str(path))
    assert len(log.samples) == 76 and log.results.scores[0].name == "llmdyno/correctness"
