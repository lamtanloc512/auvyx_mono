// Bộ tô màu cú pháp rất nhỏ, chạy lúc build (không cần thư viện, không gửi JS xuống trình duyệt).
const KEYWORDS: Record<string, string[]> = {
  ts: ["const", "let", "function", "return", "if", "else", "async", "await", "export", "import", "from", "type", "interface", "new", "for", "of", "throw", "null", "true", "false"],
  py: ["def", "return", "if", "elif", "else", "for", "in", "import", "from", "class", "with", "as", "async", "await", "None", "True", "False", "not", "and", "or", "yield", "lambda"],
  rs: ["fn", "let", "mut", "pub", "struct", "impl", "match", "return", "use", "if", "else", "for", "in", "Some", "None", "Ok", "Err", "self", "where", "async", "await"],
  go: ["func", "package", "import", "return", "if", "else", "for", "range", "var", "type", "struct", "err", "nil", "go", "defer", "chan", "select", "case"],
};

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function highlight(code: string, lang: keyof typeof KEYWORDS): string {
  const comment = lang === "py" ? "#[^\\n]*" : "//[^\\n]*";
  const re = new RegExp(
    [
      `(?<com>${comment})`,
      `(?<str>"(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*'|\`(?:\\\\.|[^\`\\\\])*\`)`,
      `(?<num>\\b\\d[\\d_.]*\\b)`,
      `(?<word>[A-Za-z_][A-Za-z0-9_]*)`,
    ].join("|"),
    "g",
  );
  const kw = new Set(KEYWORDS[lang]);
  let out = "";
  let last = 0;
  for (const m of code.matchAll(re)) {
    const i = m.index ?? 0;
    out += esc(code.slice(last, i));
    const g = m.groups!;
    const t = m[0];
    let cls = "";
    if (g.com) cls = "c";
    else if (g.str) cls = "s";
    else if (g.num) cls = "n";
    else if (kw.has(t)) cls = "k";
    else if (/^[A-Z]/.test(t)) cls = "t";
    else if (code[i + t.length] === "(" || code[i + t.length] === "!") cls = "f";
    out += cls ? `<span class="${cls}">${esc(t)}</span>` : esc(t);
    last = i + t.length;
  }
  return out + esc(code.slice(last));
}
