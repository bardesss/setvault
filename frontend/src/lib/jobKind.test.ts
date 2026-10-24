import { describe, expect, it } from "vitest";
import { jobKindKey, jobKindLabel } from "./jobKind.ts";

describe("jobKind", () => {
  it("turns dots into underscores in the i18n key", () => {
    expect(jobKindKey("email.send_email_job")).toBe("admin.jobs.kinds.email_send_email_job");
  });

  it("uses the translation when there is one", () => {
    const t = () => "Send email";
    expect(jobKindLabel("email.send_email_job", t)).toBe("Send email");
  });

  it("falls back to the raw kind", () => {
    const t = (_k: string, o?: { default?: string }) => o?.default ?? "";
    expect(jobKindLabel("weird.thing", t)).toBe("weird.thing");
  });
});
