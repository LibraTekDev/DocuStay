/**
 * Maps API/technical error messages to user-understandable messages for invitation
 * and agreement flows. Use when showing errors to the user (toast, modal, inline).
 */

/**
 * Returns a user-friendly error message for invitation/create/agreement errors.
 * Falls back to a generic message if no mapping matches.
 */
export function toUserFriendlyInvitationError(apiMessage: string | undefined | null): string {
  const raw = (apiMessage ?? "").trim().toLowerCase();
  const orig = (apiMessage ?? "").trim();

  // Pass through backend validation messages (already user-friendly)
  if (
    orig.length > 0 &&
    orig.length <= 200 &&
    !orig.includes("detail") &&
    (orig.endsWith(".") || orig.includes("required") || orig.includes("cannot") || orig.includes("must be") || orig.includes("Invalid") || orig.includes("stay starts") || orig.includes("stay ends"))
  ) {
    return orig;
  }

  // Invitation not found / expired / invalid (agreement 404)
  if (raw.includes("not found") || raw.includes("not pending") || raw.includes("expired")) {
    return "This invitation has expired or is invalid. You can't use this link to sign.";
  }

  // Server didn't return invitation code (create succeeded but no code in response)
  if (raw.includes("did not return") || raw.includes("invitation code")) {
    return "We couldn't create a valid invitation link. Please try again.";
  }

  // Network / server unavailable
  if (raw.includes("unavailable") || raw.includes("fetch") || raw.includes("network")) {
    return "The server is unavailable. Please check your connection and try again.";
  }

  // Session / auth
  if (raw.includes("session expired") || raw.includes("log in again")) {
    return "Your session expired. Please log in again.";
  }
  if (raw.includes("not authenticated") || raw.includes("unauthorized")) {
    return "Please log in to continue.";
  }

  // Validation (dates, property, unit)
  if (raw.includes("check-in") && raw.includes("past")) {
    return "Check-in date cannot be in the past.";
  }
  if (raw.includes("checkout") && raw.includes("before")) {
    return "Check-out date must be after check-in.";
  }
  if (raw.includes("property") && (raw.includes("not found") || raw.includes("inactive"))) {
    return "This property is no longer available. Please choose another property.";
  }
  if (raw.includes("select a unit") || raw.includes("unit not found")) {
    return "Please select a unit.";
  }
  if (raw.includes("guest name") && raw.includes("required")) {
    return "Guest name is required.";
  }
  if (raw.includes("start and end dates")) {
    return "Start and end dates are required.";
  }
  if (raw.includes("end date must be after start")) {
    return "End date must be after start date.";
  }
  if (raw.includes("stay starts") || raw.includes("stay ends")) {
    return orig.length > 0 && orig.length <= 200 ? orig : "Guest dates must fall within your stay.";
  }

  // Pydantic/validation (field required, type errors, etc.)
  if (raw.includes("field required") || raw.includes("value error") || raw.includes("input should be")) {
    return "Please fill in all required fields and try again.";
  }

  // Generic fallbacks
  if (raw.includes("invitation failed") || raw.includes("create invitation")) {
    return "We couldn't create the invitation. Please try again.";
  }

  return "Something went wrong. Please try again.";
}
