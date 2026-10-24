import { describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./client.ts";
import { errorMessage, formatDetail } from "./errors.ts";

describe("formatDetail", () => {
  it("passes a string through", () => {
    expect(formatDetail("unknown venue_id")).toBe("unknown venue_id");
  });

  it("joins a plain string list", () => {
    expect(formatDetail(["unknown token {Foo}", "too long"])).toBe("unknown token {Foo}; too long");
  });

  it("joins pydantic validation messages", () => {
    expect(
      formatDetail([
        { loc: ["body", "title"], msg: "Value error, title must not be blank" },
        { loc: ["body", "date"], msg: "Input should be a valid date" },
      ]),
    ).toBe("title: Value error, title must not be blank; date: Input should be a valid date");
  });

  it("never renders [object Object]", () => {
    expect(formatDetail({ msg: "bad" })).toBe("bad");
    expect(formatDetail({ other: 1 })).toBe('{"other":1}');
    expect(formatDetail([{ other: 1 }])).not.toContain("[object Object]");
  });
});

describe("errorMessage", () => {
  it("uses the detail of an ApiError without the status prefix", () => {
    expect(errorMessage(new ApiError(409, "a media root with that name exists"))).toBe(
      "a media root with that name exists",
    );
  });

  it("formats a pydantic detail list at the client boundary", () => {
    const err = new ApiError(422, formatDetail([{ loc: ["body", "port"], msg: "Input should be valid" }]));
    expect(errorMessage(err)).toBe("port: Input should be valid");
  });

  it("falls back to the message of other errors", () => {
    expect(errorMessage(new Error("boom"))).toBe("boom");
    expect(errorMessage("odd")).toBe("odd");
  });
});

describe("api() error details", () => {
  it("turns every detail shape into a readable ApiError", async () => {
    const shapes: unknown[] = [
      "plain",
      ["template must end in {Ext}"],
      [{ loc: ["body", "port"], msg: "Input should be valid" }],
    ];
    const expected = ["plain", "template must end in {Ext}", "port: Input should be valid"];
    for (const [i, detail] of shapes.entries()) {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 422 })),
      );
      await expect(api("/x")).rejects.toMatchObject({ status: 422, detail: expected[i] });
    }
    vi.unstubAllGlobals();
  });
});
