const INSTRUCTION_PATTERNS = [
  /ignore (all |any )?(previous|prior) instructions/i,
  /system prompt/i,
  /developer message/i,
  /you are (chatgpt|an ai|the assistant)/i,
  /execute (this|the following|a) (command|tool)/i,
  /tool[_ -]?call/i,
  /<\/?(system|developer|assistant|tool)>/i,
];

const CAPTURE_PATTERNS = [
  /\bremember(?: that)?\b/i,
  /\bi (?:strongly )?(?:prefer|like|dislike|hate|love|want|need)\b/i,
  /\bmy [a-z][a-z -]{1,40} (?:is|are)\b/i,
  /\bwe (?:decided|agreed|committed)\b/i,
  /\bthe decision is\b/i,
  /\b(?:always|never) (?:use|send|include|call|schedule|write)\b/i,
];

export function normalizeText(value: string): string {
  return value.normalize("NFKC").replace(/\s+/g, " ").trim();
}

export function looksLikePromptInjection(value: string): boolean {
  return INSTRUCTION_PATTERNS.some((pattern) => pattern.test(value));
}

export function shouldAutoCapture(value: string, maxChars: number): boolean {
  const normalized = normalizeText(value);
  if (normalized.length < 12 || normalized.length > maxChars) {
    return false;
  }
  if (looksLikePromptInjection(normalized)) {
    return false;
  }
  return CAPTURE_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function escapeForPrompt(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export function extractUserTexts(messages: unknown[]): string[] {
  const texts: string[] = [];
  for (const message of messages) {
    if (!message || typeof message !== "object") {
      continue;
    }
    const candidate = message as { role?: unknown; content?: unknown };
    if (candidate.role !== "user") {
      continue;
    }
    if (typeof candidate.content === "string") {
      texts.push(candidate.content);
      continue;
    }
    if (!Array.isArray(candidate.content)) {
      continue;
    }
    for (const part of candidate.content) {
      if (!part || typeof part !== "object") {
        continue;
      }
      const textPart = part as { type?: unknown; text?: unknown };
      if (
        (textPart.type === "text" || textPart.type === "input_text") &&
        typeof textPart.text === "string"
      ) {
        texts.push(textPart.text);
      }
    }
  }
  return texts;
}
