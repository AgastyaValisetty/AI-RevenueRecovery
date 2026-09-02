import { Routes, Route, useLocation } from 'react-router-dom';
import { Suspense, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useTheme } from './lib/theme-provider';
import AppShell from './components/layout/AppShell';
import routes from './routes.tsx';

function App() {
  const location = useLocation();
  const { resolvedTheme } = useTheme();

  // Scroll to top on route change
  useEffect(() => {
    document.documentElement.scrollTo({ top: 0, behavior: 'instant' });
  }, [location.pathname]);

  // Apply theme class to body
  useEffect(() => {
    document.body.setAttribute('data-theme', resolvedTheme);
    document.body.classList.toggle('dark', resolvedTheme === 'dark');
  }, [resolvedTheme]);

  return (
    <AppShell>
      <AnimatePresence initial={false}>
        <motion.main
          key={location.pathname}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="flex-1"
        >
          <Suspense
            fallback={
              <div className="flex h-full w-full items-center justify-center py-24 text-sm text-tertiary">
                Loading…
              </div>
            }
          >
            <Routes location={location}>
              {routes.map((route) => (
                <Route
                  key={route.id}
                  path={route.path!}
                  element={route.element!}
                />
              ))}
            </Routes>
          </Suspense>
        </motion.main>
      </AnimatePresence>
    </AppShell>
  );
}

export default App;
