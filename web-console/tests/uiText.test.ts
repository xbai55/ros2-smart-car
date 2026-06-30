import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const sourceFiles = [
  "src/App.tsx",
  "src/components/ColorConfigPanel.tsx",
  "src/components/ModeOperationPanel.tsx",
  "src/data/consoleData.ts",
  "src/robotApi.ts"
];

const mojibakePattern = new RegExp(
  [
    "\\u59af",
    "\\u93ac",
    "\\u6769",
    "\\u68f0\\u6ed8",
    "\\u7459",
    "\\u9429",
    "\\u7edb",
    "\\u93c3",
    "\\u6d63",
    "\\u934a",
    "\\u8930\\u64b3",
    "\\u752f",
    "\\u5b6f",
    "\\u95b0\\u5db6\\u7d1d",
    "\\u934b\\u5fd5\\u7d1d",
    "\\u6434\\u65c2\\u7d1d",
    "\\u93c9\\u30e8",
    "\\u93c8\\ue1c1",
    "\\u93c0\\u8dfa",
    "\\u5e34\\u53e3",
    "\\u59dd\\u5b2d",
    "\\u9422\\u535e",
    "\\u7f03\\u95c9",
    "\\u9286",
    "\\u7d1d",
    "\\ufffd"
  ].join("|")
);

test("visible UI source does not contain mojibake or question-mark placeholders", () => {
  for (const file of sourceFiles) {
    const source = readFileSync(join("web-console", file), "utf8");
    assert.equal(/[?]{3,}/.test(source), false, `${file} contains question-mark placeholder text`);
    assert.equal(mojibakePattern.test(source), false, `${file} contains mojibake-looking text`);
  }
});

test("color preset buttons apply the selected HSV config immediately", () => {
  const source = readFileSync(join("web-console", "src/components/ColorConfigPanel.tsx"), "utf8");

  assert.match(source, /const nextConfig = \{\s*name: preset\.name,/);
  assert.match(source, /onApply\(nextConfig\)/);
});

test("live camera feed fills the camera frame", () => {
  const css = readFileSync(join("web-console", "src/App.css"), "utf8");
  const cameraFeedBlock = css.match(/\.camera-feed\s*\{[^}]+\}/s)?.[0] ?? "";

  assert.match(cameraFeedBlock, /object-fit:\s*cover;/);
  assert.doesNotMatch(cameraFeedBlock, /object-fit:\s*contain;/);
});
