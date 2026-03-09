
export type JurisdictionState = 'NY' | 'FL' | 'CA' | 'TX' | 'WA';

export interface StayDetails {
  durationDays: number;
  paymentInvolved: boolean;
  exclusivePossession: boolean;
  checkInDate: string;
  checkOutDate: string;
}

export interface RiskFactor {
  factor: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  message: string;
  recommendation?: string;
}

export const JURISDICTION_RULES: Record<JurisdictionState, any> = {
  "NY": {
    name: "New York",
    maxSafeStayDays: 29,
    tenancyThresholdDays: 30,
    warningDays: 5,
    keyStatute: "RPAPL § 711",
    agreementType: "REVOCABLE_LICENSE",
    removalProcess: {
      guestRemoval: "Immediate with license termination",
      tenantEviction: "30-60 day court process"
    }
  },
  "FL": {
    name: "Florida",
    maxSafeStayDays: 29,
    tenancyThresholdDays: 30,
    warningDays: 5,
    keyStatute: "F.S. § 82.036",
    agreementType: "HB621_DECLARATION",
    removalProcess: {
      guestRemoval: "Immediate Sheriff removal with HB621 declaration",
      tenantEviction: "Standard eviction process"
    }
  },
  "CA": {
    name: "California",
    maxSafeStayDays: 29,
    tenancyThresholdDays: 30,
    warningDays: 5,
    keyStatute: "CA Civil Code § 1946.5",
    agreementType: "TRANSIENT_LODGER",
    removalProcess: {
      guestRemoval: "Police removal as trespasser (if single lodger)",
      tenantEviction: "30-60 day process"
    }
  },
  "TX": {
    name: "Texas",
    maxSafeStayDays: 14,
    tenancyThresholdDays: 7,
    warningDays: 3,
    keyStatute: "Property Code Chapter 92",
    agreementType: "TRANSIENT_GUEST",
    removalProcess: {
      guestRemoval: "24-hour notice",
      tenantEviction: "3-day notice + JP Court"
    }
  },
  "WA": {
    name: "Washington",
    maxSafeStayDays: 29,
    tenancyThresholdDays: 30,
    warningDays: 5,
    keyStatute: "RCW 9A.52.105",
    agreementType: "ANTI_SQUATTER_DECLARATION",
    removalProcess: {
      guestRemoval: "Police removal with RCW declaration",
      tenantEviction: "20-day notice + court"
    }
  }
};

/** State options for dropdowns (e.g. Tenant/Guest signup permanent address). Value = 2-letter code, label = full name. */
export const STATE_OPTIONS: { value: string; label: string }[] = (
  Object.entries(JURISDICTION_RULES) as [JurisdictionState, (typeof JURISDICTION_RULES)[JurisdictionState]][]
)
  .map(([code, rule]) => ({ value: code, label: rule.name }))
  .sort((a, b) => a.label.localeCompare(b.label));

export const analyzeStay = (state: JurisdictionState, details: StayDetails) => {
  const rules = JURISDICTION_RULES[state];
  if (!rules) throw new Error("Unsupported jurisdiction");

  let classification = "GUEST";
  let riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' = "LOW";
  let riskFactors: RiskFactor[] = [];

  // Duration check
  if (details.durationDays > rules.maxSafeStayDays) {
    classification = "TENANT_RISK";
    riskLevel = "CRITICAL";
    riskFactors.push({
      factor: "DURATION_EXCEEDS_LIMIT",
      severity: "CRITICAL",
      message: `Stay of ${details.durationDays} days exceeds safe limit of ${rules.maxSafeStayDays} days`,
      recommendation: "Shorten stay to below limit."
    });
  } else if (details.durationDays > rules.maxSafeStayDays - rules.warningDays) {
    classification = "TEMPORARY_OCCUPANT";
    riskLevel = "MEDIUM";
    riskFactors.push({
      factor: "APPROACHING_LIMIT",
      severity: "MEDIUM",
      message: `Stay is within ${rules.warningDays} days of limit`,
      recommendation: "Ensure check-out is strictly enforced."
    });
  }

  // Payment check
  if (details.paymentInvolved) {
    const severity = state === "TX" ? "HIGH" : "MEDIUM";
    riskFactors.push({
      factor: "PAYMENT_INVOLVED",
      severity,
      message: state === "TX" ? "Any payment in Texas can create tenant status" : "Payment may resemble rent",
      recommendation: "Avoid any exchange of money or labor."
    });
    if (riskLevel !== "CRITICAL") riskLevel = severity as any;
  }

  // Risk Score
  const weights: Record<string, number> = {
    DURATION_EXCEEDS_LIMIT: 50,
    APPROACHING_LIMIT: 20,
    PAYMENT_INVOLVED: 25,
    EXCLUSIVE_POSSESSION: 20
  };
  let riskScore = 0;
  riskFactors.forEach(rf => riskScore += weights[rf.factor] || 10);
  riskScore = Math.min(100, riskScore);

  return {
    jurisdiction: { state, name: rules.name, keyStatute: rules.keyStatute },
    classification: { stayType: classification, riskLevel, riskScore },
    limits: { 
      maxSafeStayDays: rules.maxSafeStayDays, 
      withinLimit: details.durationDays <= rules.maxSafeStayDays,
      daysUntilRisk: Math.max(0, rules.maxSafeStayDays - details.durationDays)
    },
    riskFactors,
    legal: {
      agreementType: rules.agreementType,
      removalProcess: rules.removalProcess
    },
    canProceed: riskLevel !== "CRITICAL"
  };
};
