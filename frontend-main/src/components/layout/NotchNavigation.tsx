import { motion } from 'framer-motion';
import { useLocation, useNavigate } from 'react-router-dom';
import { useNavigation } from './navigation-context';
import type { NavItem } from '../../routes';

/**
 * NotchNavigation — floating asymmetric-corner navigation bar.
 *
 * Signature navigation element: a pill-shaped floating bar with
 * asymmetric corner treatment and animated active state that tracks
 * the current route. The bar "notches" inward with a custom SVG clip.
 */
export function NotchNavigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const { navSections } = useNavigation();

  const allItems = navSections.flatMap((s) => s.items);
  const activeItem = allItems.find((item) => item.path === location.pathname);

  // Group items for the floating bar — only show top-level items in the bar
  // Detailed section groups live in the page sidebar
  const topLevelItems = allItems.filter((item) =>
    ['overview', 'comparison', 'sara-attempts', 'failures', 'rail-health', 'cases', 'simulation', 'audit'].includes(
      item.id,
    ),
  );

  return (
    <nav
      className="relative hidden md:flex items-center gap-1.5 bg-panel border border-border-panel rounded-full px-2 py-1.5 shadow-subtle"
      aria-label="Main navigation"
    >
      {/* Chartreuse accent that slides under the active item */}
      <motion.div
        className="absolute inset-0 rounded-full -z-10"
        initial={false}
        animate={{
          opacity: activeItem ? 0.12 : 0,
        }}
      />

      {topLevelItems.map((item) => {
        const isActive = activeItem?.path === item.path;
        const Icon = item.icon;

        return (
          <NavButton
            key={item.path}
            item={item}
            icon={Icon}
            isActive={isActive}
            onClick={() => navigate(item.path)}
          />
        );
      })}
    </nav>
  );
}

interface NavButtonProps {
  item: NavItem;
  icon: NavItem['icon'];
  isActive: boolean;
  onClick: () => void;
}

function NavButton({ item, icon: Icon, isActive, onClick }: NavButtonProps) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      className="relative flex items-center gap-2 px-3.5 py-2 rounded-full text-sm font-medium transition-all duration-250 focus:outline-none focus:ring-2 focus:ring-chartreuse focus:ring-offset-2 focus:ring-offset-canvas"
      style={{
        color: isActive ? 'var(--bg-canvas)' : 'var(--text-secondary)',
        backgroundColor: isActive ? 'var(--chartreuse)' : 'transparent',
        borderRadius: '9999px',
      }}
      whileHover={{
        scale: 1.03,
        color: 'var(--text-primary)',
        backgroundColor: isActive
          ? 'var(--chartreuse-dim)'
          : 'rgba(201, 243, 91, 0.08)',
      }}
      whileTap={{ scale: 0.97 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
    >
      <motion.span
        animate={{ rotate: isActive ? 360 : 0 }}
        transition={{ duration: 0.5, ease: 'easeInOut' }}
      >
        <Icon size={16} strokeWidth={isActive ? 2.5 : 2} />
      </motion.span>
      <span className="hidden sm:inline">{item.label}</span>

      {isActive && (
        <motion.div
          layoutId="active-glow"
          className="absolute -inset-0.5 rounded-full -z-10"
          style={{
            background: 'radial-gradient(circle at center, rgba(201, 243, 91, 0.4) 0%, transparent 70%)',
          }}
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.8 }}
        />
      )}
    </motion.button>
  );
}
