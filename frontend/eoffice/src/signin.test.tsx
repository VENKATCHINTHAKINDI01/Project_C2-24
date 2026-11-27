import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SignIn } from "./components/SignIn";
import type { Api } from "./api";

describe("sign-in page", () => {
  it("renders the controls, the banner text of the sandbox and the no-password note", () => {
    const api = { profiles: () => new Promise(() => {}) } as unknown as Api;
    const html = renderToStaticMarkup(<SignIn api={api} onSignIn={() => {}} size="normal" onSize={() => {}} />);
    expect(html).toContain("eFile Sandbox");
    expect(html).toContain("No password, DSC, eSign or Parichay");
    expect(html).toContain("हिन्दी");
    expect(html).toContain('aria-label="Text size"');
    expect(html).not.toMatch(/NIC/);
  });
});
