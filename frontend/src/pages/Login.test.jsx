import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { AuthProvider, useAuth } from "../auth";
import Login from "./Login";

const USER = { id: 1, username: "admin", role: "admin" };

function Screen() {
  const { status, user } = useAuth();
  if (status !== "ready") return <p>loading</p>;
  return user ? <p>Welcome {user.username}</p> : <Login />;
}

function renderLogin(status = {}) {
  vi.spyOn(api, "authStatus").mockResolvedValue({ data: { setup_required: false, user: null, sso: null, ...status } });
  render(<AuthProvider><Screen /></AuthProvider>);
}

describe("Login", () => {
  beforeEach(() => window.history.replaceState(null, "", "/"));

  it("signs in with a password", async () => {
    const login = vi.spyOn(api, "login").mockResolvedValue({ data: { user: USER } });
    renderLogin();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), " admin ");
    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(login).toHaveBeenCalledWith({ username: "admin", password: "correct horse" });
    expect(await screen.findByText("Welcome admin")).toBeInTheDocument();
  });

  it("shows the error and clears the password when sign-in fails", async () => {
    vi.spyOn(api, "login").mockRejectedValue(new Error("Invalid username or password"));
    renderLogin();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("asks for a two-factor code, then signs in", async () => {
    vi.spyOn(api, "login").mockResolvedValue({ data: { mfa_required: true, mfa_token: "tok" } });
    const second = vi.spyOn(api, "loginSecondFactor").mockResolvedValue({ data: { user: USER } });
    renderLogin();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const code = await screen.findByLabelText("Authentication code");
    const verify = screen.getByRole("button", { name: "Verify" });
    await user.type(code, "12345");
    expect(verify).toBeDisabled(); // six digits needed
    await user.type(code, "6");
    await user.click(verify);
    expect(second).toHaveBeenCalledWith({ mfa_token: "tok", code: "123456" });
    expect(await screen.findByText("Welcome admin")).toBeInTheDocument();
  });

  it("accepts a recovery code instead", async () => {
    vi.spyOn(api, "login").mockResolvedValue({ data: { mfa_required: true, mfa_token: "tok" } });
    const second = vi.spyOn(api, "loginSecondFactor").mockResolvedValue({ data: { user: USER } });
    renderLogin();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(await screen.findByRole("button", { name: "Use a recovery code" }));
    await user.type(screen.getByLabelText("Recovery code"), "abcde-12345");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(second).toHaveBeenCalledWith({ mfa_token: "tok", code: "abcde-12345" });
  });

  it("goes back to the password step when the two-factor sign-in expires", async () => {
    vi.spyOn(api, "login").mockResolvedValue({ data: { mfa_required: true, mfa_token: "tok" } });
    vi.spyOn(api, "loginSecondFactor").mockRejectedValue(new Error("Sign-in expired, start again"));
    renderLogin();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.type(await screen.findByLabelText("Authentication code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in expired, start again");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("creates the first admin with the setup token, checking the password locally first", async () => {
    const setup = vi.spyOn(api, "setupAdmin").mockResolvedValue({ data: { user: USER } });
    renderLogin({ setup_required: true });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Setup token"), "token-1");
    await user.type(screen.getByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.type(screen.getByLabelText("Confirm password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 12 characters");
    expect(setup).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "a-long-passphrase");
    await user.clear(screen.getByLabelText("Confirm password"));
    await user.type(screen.getByLabelText("Confirm password"), "a-long-passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() =>
      expect(setup).toHaveBeenCalledWith({ username: "admin", password: "a-long-passphrase", setup_token: "token-1" }));
  });

  it("offers single sign-on when it's configured, and shows its errors", async () => {
    window.history.replaceState(null, "", "/?sso_error=Your+account+is+disabled");
    renderLogin({ sso: { enabled: true, label: "Sign in with Okta" } });
    expect(await screen.findByRole("link", { name: "Sign in with Okta" })).toHaveAttribute("href", api.ssoLoginUrl);
    expect(screen.getByRole("alert")).toHaveTextContent("Your account is disabled");
    expect(window.location.search).toBe("");
  });

  it("drops back to sign-in when any request finds the session expired", async () => {
    vi.spyOn(api, "authStatus").mockResolvedValue({ data: { setup_required: false, user: USER } });
    render(<AuthProvider><Screen /></AuthProvider>);
    expect(await screen.findByText("Welcome admin")).toBeInTheDocument();
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}", { status: 401 }));
    await expect(api.getAgents()).rejects.toThrow();
    expect(await screen.findByText("Your session has expired. Sign in again.")).toBeInTheDocument();
  });
});
