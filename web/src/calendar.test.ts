import { describe as suite, expect, it } from "vitest";
import { googleCalendarUrl } from "./util";

suite("googleCalendarUrl", () => {
  it("builds a 1-hour event preceding a deadline ISO", () => {
    const url = googleCalendarUrl({
      title: "Google Online Assessment",
      deadlineIso: "2026-10-28T18:00:00Z",
      details: "Complete by 6 PM UTC",
      location: "https://assessment.google.com/test",
    });
    expect(url).not.toBeNull();
    const parsed = new URL(url!);
    expect(parsed.origin).toBe("https://calendar.google.com");
    expect(parsed.pathname).toBe("/calendar/render");
    expect(parsed.searchParams.get("action")).toBe("TEMPLATE");
    expect(parsed.searchParams.get("text")).toBe("Google Online Assessment");
    expect(parsed.searchParams.get("dates")).toBe("20261028T170000Z/20261028T180000Z");
    expect(parsed.searchParams.get("details")).toBe("Complete by 6 PM UTC");
    expect(parsed.searchParams.get("location")).toBe("https://assessment.google.com/test");
  });

  it("handles explicit start and end ISO timestamps", () => {
    const url = googleCalendarUrl({
      title: "Final Interview",
      startIso: "2026-11-01T10:00:00Z",
      endIso: "2026-11-01T11:30:00Z",
    });
    expect(url).not.toBeNull();
    const parsed = new URL(url!);
    expect(parsed.searchParams.get("dates")).toBe("20261101T100000Z/20261101T113000Z");
    expect(parsed.searchParams.get("text")).toBe("Final Interview");
  });

  it("returns null on missing or invalid dates", () => {
    expect(googleCalendarUrl({ title: "No date" })).toBeNull();
    expect(googleCalendarUrl({ title: "Bad date", deadlineIso: "invalid-date" })).toBeNull();
    expect(
      googleCalendarUrl({
        title: "End before start",
        startIso: "2026-11-01T12:00:00Z",
        endIso: "2026-11-01T10:00:00Z",
      })
    ).toBeNull();
  });
});
