import { lazy } from 'react';
import type { RouteObject } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';

// Lazy-loaded route components
const Overview = lazy(() => import('./pages/Overview'));
const Comparison = lazy(() => import('./pages/Comparison'));
const CaseQueue = lazy(() => import('./pages/CaseQueue'));
const CaseDetail = lazy(() => import('./pages/CaseDetail'));
const Simulation = lazy(() => import('./pages/Simulation'));
const Failures = lazy(() => import('./pages/Failures'));
const RailHealth = lazy(() => import('./pages/RailHealth'));
const Audit = lazy(() => import('./pages/Audit'));
const People = lazy(() => import('./pages/People'));
const PersonDetail = lazy(() => import('./pages/PersonDetail'));
const Ledger = lazy(() => import('./pages/Ledger'));
const Merchants = lazy(() => import('./pages/Merchants'));
const SaraAttempts = lazy(() => import('./pages/SaraAttempts'));

// ── Navigation items ───────────────────────────────────

export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  path: string;
  section: 'overview' | 'analysis' | 'operations' | 'reference';
}

// Route definitions matching the NotchNavigation
export const routes: RouteObject[] = [
  { path: '/', element: <Overview />, id: 'overview' },
  { path: '/comparison', element: <Comparison />, id: 'comparison' },
  { path: '/cases', element: <CaseQueue />, id: 'cases' },
  { path: '/cases/:caseId', element: <CaseDetail />, id: 'case-detail' },
  { path: '/simulation', element: <Simulation />, id: 'simulation' },
  { path: '/failures', element: <Failures />, id: 'failures' },
  { path: '/rail-health', element: <RailHealth />, id: 'rail-health' },
  { path: '/audit', element: <Audit />, id: 'audit' },
  { path: '/people', element: <People />, id: 'people' },
  { path: '/people/:personId', element: <PersonDetail />, id: 'person-detail' },
  { path: '/ledger', element: <Ledger />, id: 'ledger' },
  { path: '/merchants', element: <Merchants />, id: 'merchants' },
  { path: '/sara-attempts', element: <SaraAttempts />, id: 'sara-attempts' },
];

export default routes;
