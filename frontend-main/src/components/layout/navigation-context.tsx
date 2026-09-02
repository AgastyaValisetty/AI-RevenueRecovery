import { createContext, useContext, useState, ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Home,
  TrendingUp,
  BarChart3,
  PlayCircle,
  AlertCircle,
  Activity,
  FileText,
  Users,
  Wallet,
  Store,
  LifeBuoy,
  Target,
} from 'lucide-react';
import type { NavItem } from '../../routes';

interface NavigationContextValue {
  navSections: NavSection[];
  activeItem: NavItem | null;
  setActiveItem: (item: NavItem) => void;
}

interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
}

const NavigationContext = createContext<NavigationContextValue | undefined>(undefined);

const navSections: NavSection[] = [
  {
    id: 'overview',
    label: 'Observatory',
    items: [
      { id: 'overview', label: 'Overview', icon: Home, path: '/', section: 'overview' },
    ],
  },
  {
    id: 'analysis',
    label: 'Analysis',
    items: [
      { id: 'comparison', label: 'Recovery Curve', icon: TrendingUp, path: '/comparison', section: 'analysis' },
      { id: 'failures', label: 'Failures', icon: AlertCircle, path: '/failures', section: 'analysis' },
      { id: 'rail-health', label: 'Rail Health', icon: Activity, path: '/rail-health', section: 'analysis' },
    ],
  },
  {
    id: 'operations',
    label: 'Operations',
    items: [
      { id: 'cases', label: 'Dispatch Board', icon: BarChart3, path: '/cases', section: 'operations' },
      { id: 'simulation', label: 'Simulation', icon: PlayCircle, path: '/simulation', section: 'operations' },
      { id: 'audit', label: 'Audit Log', icon: FileText, path: '/audit', section: 'operations' },
    ],
  },
  {
    id: 'reference',
    label: 'Reference',
    items: [
      { id: 'people', label: 'People', icon: Users, path: '/people', section: 'reference' },
      { id: 'ledger', label: 'Ledger', icon: Wallet, path: '/ledger', section: 'reference' },
      { id: 'merchants', label: 'Merchants', icon: Store, path: '/merchants', section: 'reference' },
      { id: 'sara-attempts', label: 'SARA Attempts', icon: Target, path: '/sara-attempts', section: 'reference' },
      { id: 'support', label: 'Documentation', icon: LifeBuoy, path: '/support', section: 'reference' },
    ],
  },
];

export function NavigationProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [activeItem, setActiveItem] = useState<NavItem | null>(null);

  // Sync active item with current location
  const currentItem = navSections
    .flatMap((s) => s.items)
    .find((item) => item.path === location.pathname);

  const handleNavigate = (item: NavItem) => {
    setActiveItem(item);
    navigate(item.path);
  };

  return (
    <NavigationContext.Provider
      value={{
        navSections,
        activeItem: currentItem || activeItem,
        setActiveItem: handleNavigate,
      }}
    >
      {children}
    </NavigationContext.Provider>
  );
}

export function useNavigation() {
  const ctx = useContext(NavigationContext);
  if (!ctx) {
    throw new Error('useNavigation must be used within NavigationProvider');
  }
  return ctx;
}
