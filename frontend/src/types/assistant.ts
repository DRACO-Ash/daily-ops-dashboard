export type ActionUrgency = "high" | "medium" | "low";

export interface ApplicableProcedure {
  procedure_id: string | null;
  name: string;
  reason: string;
}

export interface NextAction {
  action: string;
  urgency: ActionUrgency | string;
  deadline: string | null;
  rationale: string;
}

export interface StructuredEvaluation {
  summary: string;
  applicable_procedures: ApplicableProcedure[];
  next_actions: NextAction[];
  open_questions: string[];
}

export interface AssistantEvaluation {
  id: string;
  notification_id: string;
  summary: string;
  structured: StructuredEvaluation;
  procedures_used: string[];
  model: string;
  error: string | null;
  evaluated_at: string;
}
