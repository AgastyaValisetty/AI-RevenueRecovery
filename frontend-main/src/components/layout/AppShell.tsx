import { useState, useEffect, ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { motion, useScroll, useTransform } from 'framer-motion';
import { NotchNavigation } from './NotchNavigation';
import { NavigationProvider } from './navigation-context';
import { Toaster } from '../ui/Toaster';

// Note: NotchNavigation is a self-contained component for top-level route switching.

interface AppShellProps {
  children: ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  // Close sidebar on mobile route change
  useEffect(() => {
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
    }
  }, [location.pathname]);

  const { scrollYProgress } = useScroll();
  const headerOpacity = useTransform(scrollYProgress, [0, 0.05], [1, 0.8]);
  const headerBlur = useTransform(scrollYProgress, [0, 0.1], [0, 12]);
  const headerBackdropFilter = useTransform(headerBlur, (v) => `blur(${v}px)`);

  return (
    <NavigationProvider>
      <div className="relative flex min-h-screen bg-canvas text-primary">
        {/* Scroll progress bar */}
        <div className="fixed top-0 left-0 right-0 h-0.5 bg-border-subtle">
          <motion.div
            className="h-full bg-chartreuse origin-left"
            style={{ scaleX: scrollYProgress }}
          />
        </div>

        {/* Top Navigation Bar */}
        <motion.header
          className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 h-16 bg-elevated/80 border-b border-subtle backdrop-blur-xs"
          style={{ opacity: headerOpacity, backdropFilter: headerBackdropFilter }}
        >
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="md:hidden p-2 rounded-md text-tertiary hover:text-primary hover:bg-panel transition-colors"
              aria-label="Toggle navigation"
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {sidebarOpen ? (
                  <>
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </>
                ) : (
                  <>
                    <line x1="3" y1="6" x2="21" y2="6" />
                    <line x1="3" y1="12" x2="21" y2="12" />
                    <line x1="3" y1="18" x2="21" y2="18" />
                  </>
                )}
              </svg>
            </button>
          </div>

          <NotchNavigation />
        </motion.header>

        {/* Sidebar overlay for mobile */}
        {sidebarOpen && (
          <motion.div
            className="fixed inset-0 z-40 md:hidden bg-canvas/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Main content */}
        <main className="pt-16 min-h-screen">
          <div className="mx-auto max-w-[1440px] px-6 py-8 md:py-10 md:px-8">
            {children}
          </div>
        </main>

        <Toaster />
      </div>
    </NavigationProvider>
  );
}
