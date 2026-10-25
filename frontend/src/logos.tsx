// Vendor and model-family logos from @lobehub/icons-static-svg (MIT). The marks themselves are trademarks of their
// owners, shown only to identify which provider or model a profile uses (see NOTICE.md).
// Imported as raw SVG text, so only these files end up in the bundle; monochrome marks use currentColor and follow
// the theme.
import { Server } from "lucide-react";
import ai2 from "@lobehub/icons-static-svg/icons/ai2-color.svg?raw";
import anthropic from "@lobehub/icons-static-svg/icons/anthropic.svg?raw";
import baidu from "@lobehub/icons-static-svg/icons/baidu-color.svg?raw";
import cerebras from "@lobehub/icons-static-svg/icons/cerebras-color.svg?raw";
import cohere from "@lobehub/icons-static-svg/icons/cohere-color.svg?raw";
import deepseek from "@lobehub/icons-static-svg/icons/deepseek-color.svg?raw";
import fireworks from "@lobehub/icons-static-svg/icons/fireworks-color.svg?raw";
import gemini from "@lobehub/icons-static-svg/icons/gemini-color.svg?raw";
import gemma from "@lobehub/icons-static-svg/icons/gemma-color.svg?raw";
import groq from "@lobehub/icons-static-svg/icons/groq.svg?raw";
import huggingface from "@lobehub/icons-static-svg/icons/huggingface-color.svg?raw";
import ibm from "@lobehub/icons-static-svg/icons/ibm.svg?raw";
import kimi from "@lobehub/icons-static-svg/icons/kimi-color.svg?raw";
import lg from "@lobehub/icons-static-svg/icons/lg-color.svg?raw";
import meta from "@lobehub/icons-static-svg/icons/meta-color.svg?raw";
import microsoft from "@lobehub/icons-static-svg/icons/microsoft-color.svg?raw";
import minimax from "@lobehub/icons-static-svg/icons/minimax-color.svg?raw";
import mistral from "@lobehub/icons-static-svg/icons/mistral-color.svg?raw";
import nvidia from "@lobehub/icons-static-svg/icons/nvidia-color.svg?raw";
import openai from "@lobehub/icons-static-svg/icons/openai.svg?raw";
import openrouter from "@lobehub/icons-static-svg/icons/openrouter.svg?raw";
import qwen from "@lobehub/icons-static-svg/icons/qwen-color.svg?raw";
import together from "@lobehub/icons-static-svg/icons/together-color.svg?raw";
import xai from "@lobehub/icons-static-svg/icons/xai.svg?raw";
import zai from "@lobehub/icons-static-svg/icons/zai.svg?raw";

const LOGOS: Record<string, string> = {
  openai, anthropic, google: gemini, gemini, gemma, deepseek, moonshot: kimi, kimi, zai, qwen, minimax, xai, mistral, openrouter, groq,
  together, fireworks, cerebras, meta, nvidia, microsoft, ibm, baidu, ai2, lg, cohere, huggingface,
};

/** Model maker from a GGUF architecture or model name (mirrors ARCH_VENDOR in llmdyno/judge/judge.py). */
const FAMILY: [string, string][] = [
  ["gpt-oss", "openai"], ["qwen", "qwen"], ["gemma", "gemma"], ["llama", "meta"], ["mistral", "mistral"], ["ministral", "mistral"],
  ["devstral", "mistral"], ["deepseek", "deepseek"], ["glm", "zai"], ["minimax", "minimax"], ["kimi", "moonshot"], ["phi", "microsoft"],
  ["granite", "ibm"], ["nemotron", "nvidia"], ["ernie", "baidu"], ["olmo", "ai2"], ["smollm", "huggingface"], ["exaone", "lg"],
  ["command", "cohere"], ["grok", "xai"],
];

/** API model ids that do not contain an open-weights family name. */
const CLOUD: [RegExp, string][] = [[/\b(gpt|o[134]\b|o[134]-|chatgpt|codex)/, "openai"], [/claude|opus|sonnet|haiku|fable/, "anthropic"], [/gemini/, "google"],
  [/grok/, "xai"], [/kimi|moonshot/, "moonshot"], [/glm|zhipu/, "zai"], [/minimax|abab/, "minimax"], [/deepseek/, "deepseek"], [/mistral|codestral|magistral/, "mistral"]];
function cloudHint(...hints: (string | null | undefined)[]) {
  for (const h of hints) {
    const s = (h || "").toLowerCase();
    const hit = s && CLOUD.find(([re]) => re.test(s));
    if (hit) return hit[1];
  }
  return null;
}

export function familyOf(...hints: (string | null | undefined)[]) {
  for (const h of hints) {
    const s = (h || "").toLowerCase();
    if (!s) continue;
    const hit = FAMILY.find(([k]) => s.includes(k));
    if (hit) return hit[1];
  }
  return null;
}

/** A logo in a neutral rounded tile; unknown vendors (custom endpoints) get a generic server icon. */
export function Logo({ id, size = 30, title }: { id?: string | null; size?: number; title?: string }) {
  const svg = id ? LOGOS[id] : undefined;
  return (
    <span className="logo-tile" style={{ width: size, height: size, fontSize: Math.round(size * 0.6) }} title={title} aria-hidden={!title} role={title ? "img" : undefined} aria-label={title}>
      {svg ? <span className="logo-svg" dangerouslySetInnerHTML={{ __html: svg }} /> : <Server size={Math.round(size * 0.5)} />}
    </span>
  );
}

export const hasLogo = (id?: string | null) => !!id && id in LOGOS;

const HOSTS = new Set(["openrouter", "groq", "together", "fireworks", "cerebras", "custom"]);

/** The logo for a profile, from any of the shapes the API returns (profile objects or result labels). */
export function profileLogo(p: any): string | null {
  if (!p) return null;
  const vendor = p.vendor ?? p.provider?.vendor;
  if (p.kind && p.kind !== "local") {
    if (vendor && !HOSTS.has(vendor)) return vendor;
    // hosts serve other labs' models: show the lab, falling back to the host
    return familyOf(p.remote_model, p.model, p.name) || cloudHint(p.remote_model, p.model, p.name) || (vendor === "custom" ? null : vendor) || null;
  }
  const m = p.model && typeof p.model === "object" ? p.model : null;
  // the model name wins over the architecture: SmolLM ships as "llama", Kimi as "deepseek2"
  return familyOf(m?.name, m?.repo, typeof p.model === "string" ? p.model : null) || familyOf(p.arch, m?.meta?.arch) || familyOf(p.name);
}

/** Logo for a local model record (library, downloads, hub search results). */
export const modelLogo = (m: any) => familyOf(m?.name, m?.repo) || familyOf(m?.meta?.arch, m?.arch);

export function LogoName({ id, children, size = 18, title }: { id?: string | null; children: React.ReactNode; size?: number; title?: string }) {
  return (
    <span className="logo-inline" title={title}>
      <Logo id={id} size={size} />
      <span>{children}</span>
    </span>
  );
}

/** Logos as image URLs for chart labels (ECharts rich text cannot render inline SVG markup). */
const urlCache = new Map<string, string>();
export function logoUrl(id: string | null | undefined, color: string) {
  if (!id || !LOGOS[id]) return null;
  const k = id + color;
  if (!urlCache.has(k)) {
    const svg = LOGOS[id].replace(/currentColor/g, color).replace(/width="1em"/, 'width="64"').replace(/height="1em"/, 'height="64"');
    urlCache.set(k, "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg));
  }
  return urlCache.get(k)!;
}

/** ECharts rich-text styles for every logo: use as axisLabel.rich and format labels with chartLabel(). */
export function logoRich(color: string, size = 14) {
  const rich: Record<string, any> = { n: {} };
  for (const id of Object.keys(LOGOS)) rich["l_" + id.replace(/\W/g, "_")] = { height: size, width: size, align: "center", backgroundColor: { image: logoUrl(id, color) } };
  return rich;
}
export const chartLabel = (id: string | null | undefined, text: string) =>
  id && LOGOS[id] ? `{l_${id.replace(/\W/g, "_")}|}  {n|${text.replace(/[{}|]/g, "")}}` : `{n|${text.replace(/[{}|]/g, "")}}`;
