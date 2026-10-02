/**
 * Names for the API's types.
 *
 * schema.d.ts is generated from the backend's OpenAPI document
 * (npm run generate:api). This file only gives the generated types
 * shorter names; it declares nothing of its own, so the frontend cannot
 * disagree with the backend about the shape of a response.
 */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["Me"];
export type AuthConfig = Schemas["AuthConfig"];
export type ApiToken = Schemas["ApiTokenOut"];
export type ApiTokenCreated = Schemas["ApiTokenCreated"];
export type Project = Schemas["ProjectOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type Endpoint = Schemas["EndpointOut"];
export type Rule = Schemas["RuleOut"];
export type RuleCreate = Schemas["RuleCreate"];
export type Secret = Schemas["SecretOut"];
export type TestCase = Schemas["TestCaseOut"];
export type TestCaseWrite = Schemas["TestCaseWrite"];
export type Run = Schemas["RunOut"];
export type RunDetail = Schemas["RunDetail"];
export type RunDifference = Schemas["RunDifference"];
export type CaseResultSummary = Schemas["CaseResultSummary"];
export type CaseResultDetail = Schemas["CaseResultDetail"];
export type StepResult = Schemas["StepResultOut"];
export type Difference = Schemas["DifferenceOut"];
export type RunSummary = Schemas["RunSummary"];
export type Finding = Schemas["Finding"];
export type Analysis = Schemas["AnalysisOut"];
export type Features = Schemas["Features"];
