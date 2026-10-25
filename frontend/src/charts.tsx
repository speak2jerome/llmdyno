// ECharts wrapper themed from the CSS tokens, so charts follow light/dark mode.
import { BarChart, BoxplotChart, HeatmapChart, LineChart, RadarChart, ScatterChart } from "echarts/charts";
import {
  DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, RadarComponent, TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { cssVar, PALETTE } from "./format";
import { useTheme } from "./theme";

echarts.use([BarChart, LineChart, ScatterChart, HeatmapChart, RadarChart, BoxplotChart, GridComponent, TooltipComponent,
  LegendComponent, VisualMapComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, RadarComponent, CanvasRenderer]);

export function themeColors() {
  return {
    text: cssVar("--text"), text2: cssVar("--text-2"), text3: cssVar("--text-3"), border: cssVar("--border"),
    surface: cssVar("--surface"), surface3: cssVar("--surface-3"), accent: cssVar("--accent"), ok: cssVar("--ok"),
    warn: cssVar("--warn"), danger: cssVar("--danger"), info: cssVar("--info"), palette: PALETTE.map(cssVar),
  };
}

export function baseOption() {
  const c = themeColors();
  return {
    color: c.palette,
    textStyle: { fontFamily: "Inter Variable, Segoe UI, sans-serif", color: c.text2 },
    tooltip: {
      backgroundColor: c.surface, borderColor: c.border, textStyle: { color: c.text, fontSize: 12 },
      extraCssText: "box-shadow: 0 8px 24px rgba(0,0,0,.16); border-radius: 8px;",
    },
    legend: { textStyle: { color: c.text2 }, icon: "roundRect", itemWidth: 10, itemHeight: 10 },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
  };
}

export function axis(type: "value" | "category" | "log", extra: any = {}) {
  const c = themeColors();
  return {
    type, axisLine: { lineStyle: { color: c.border } }, axisTick: { show: false },
    axisLabel: { color: c.text3, fontSize: 11 }, splitLine: { lineStyle: { color: c.border, type: "dashed" } },
    nameTextStyle: { color: c.text3, fontSize: 11 }, ...extra,
  };
}

export function Chart({ option, height = 320, onClick, style }: { option: any | ((c: ReturnType<typeof themeColors>) => any); height?: number; onClick?: (p: any) => void; style?: React.CSSProperties }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const { resolved } = useTheme();
  const clickRef = useRef(onClick);
  clickRef.current = onClick;
  useEffect(() => {
    if (!ref.current) return;
    const ch = echarts.init(ref.current, undefined, { renderer: "canvas" });
    inst.current = ch;
    ch.on("click", (p) => clickRef.current?.(p));
    const ro = new ResizeObserver(() => ch.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      ch.dispose();
      inst.current = null;
    };
  }, []);
  useEffect(() => {
    const ch = inst.current;
    if (!ch) return;
    const o = typeof option === "function" ? option(themeColors()) : option;
    const base: any = baseOption();
    // merge themed defaults into per-chart legend/tooltip settings instead of letting them replace the theme
    const merged: any = { ...base, ...o };
    for (const k of ["legend", "tooltip", "textStyle"]) {
      if (o?.[k] && typeof o[k] === "object" && !Array.isArray(o[k])) {
        merged[k] = { ...base[k], ...o[k], ...(base[k]?.textStyle || o[k].textStyle ? { textStyle: { ...base[k]?.textStyle, ...o[k].textStyle } } : {}) };
      }
    }
    ch.setOption(merged, { notMerge: true });
  }, [option, resolved]);
  return <div ref={ref} style={{ height, width: "100%", ...style }} />;
}
