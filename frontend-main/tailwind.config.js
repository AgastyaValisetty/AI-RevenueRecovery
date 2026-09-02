import plugin from 'tailwindcss/plugin';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Canonical dark financial palette
        canvas: '#0A0D0C',
        elevated: '#111615',
        panel: '#1A211F',
        panelHover: '#212926',
        border: '#2A3330',
        borderHover: '#3A4542',

        // Accent — chartreuse intelligence
        chartreuse: '#C9F35B',
        'chartreuse-dim': '#A3D845',
        'chartreuse-bg': 'rgba(201, 243, 91, 0.10)',
        'chartreuse-border': 'rgba(201, 243, 91, 0.30)',

        // Money color
        money: '#E5A35D',
        'money-dim': '#C98A50',

        // Text hierarchy
        text: {
          primary: '#F5F7F6',
          secondary: '#9CA3A0',
          muted: '#6B6F6D',
          disabled: '#4A4D4C',
        },

        // Status
        success: '#10B981',
        warning: '#F59E0B',
        error: '#EF4444',
        info: '#38BDF8',
      },

      fontFamily: {
        sans: ['Satoshi', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
        display: ['Geist', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
      },

      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.75rem' }],
        xs: ['0.75rem', { lineHeight: '1rem' }],
        sm: ['0.875rem', { lineHeight: '1.25rem' }],
        base: ['1rem', { lineHeight: '1.5rem' }],
        lg: ['1.125rem', { lineHeight: '1.75rem' }],
        xl: ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem' }],
        '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
        '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
        '5xl': ['3rem', { lineHeight: '3.5rem' }],
        '6xl': ['3.75rem', { lineHeight: '1' }],
        '7xl': ['4.5rem', { lineHeight: '1' }],
        '8xl': ['6rem', { lineHeight: '1' }],
      },

      letterSpacing: {
        tighter: '-0.02em',
        tight: '-0.01em',
        normal: '0',
        wide: '0.025em',
        wider: '0.05em',
      },

      spacing: {
        // 4px grid system
        px: '1px',
        0.5: '2px',
        1: '4px',
        1.5: '6px',
        2: '8px',
        2.5: '10px',
        3: '12px',
        3.5: '14px',
        4: '16px',
        5: '20px',
        6: '24px',
        7: '28px',
        8: '32px',
        9: '36px',
        10: '40px',
        11: '44px',
        12: '48px',
        14: '56px',
        16: '64px',
        20: '80px',
        24: '96px',
        28: '112px',
        32: '128px',
      },

      borderRadius: {
        sm: '6px',
        md: '10px',
        lg: '14px',
        xl: '20px',
        '2xl': '28px',
        '3xl': '36px',
        full: '9999px',
      },

      boxShadow: {
        subtle: '0 4px 20px -2px rgba(0, 0, 0, 0.50)',
        glow: '0 0 30px rgba(201, 243, 91, 0.20)',
        'glow-strong': '0 0 40px rgba(201, 243, 91, 0.35)',
        inset: 'inset 0 1px 0 rgba(255, 255, 255, 0.04)',
      },

      transitionProperty: {
        'colors': 'color, background-color, border-color, text-decoration-color, fill, stroke',
        'opacity': 'opacity',
        'transform': 'transform',
      },

      keyframes: {
        'pulse-subtle': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        'pulse-glow': {
          '0%': { boxShadow: '0 0 0 0 rgba(201, 243, 91, 0.4)' },
          '70%': { boxShadow: '0 0 0 8px rgba(201, 243, 91, 0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(201, 243, 91, 0)' },
        },
        'scan': {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100%)' },
        },
        'shimmer': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(200%)' },
        },
      },

      animation: {
        'pulse-subtle': 'pulse-subtle 2s ease-in-out infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'scan': 'scan 2s linear infinite',
        'shimmer': 'shimmer 1.5s ease-in-out infinite',
      },

      backdropBlur: {
        xs: '2px',
        sm: '4px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
    },

    container: {
      center: true,
      padding: '32px',
    },
  },

  plugins: [
    // Custom utility plugins
    plugin(({ addUtilities }) => {
      addUtilities({
        '.text-balance': {
          'text-wrap': 'balance',
        },
        '.text-balance-all': {
          'text-wrap': 'balance',
        },
      });
    }),

    plugin(({ addComponents }) => {
      addComponents({
        // Scrollbar
        '::.-webkit-scrollbar': {
          width: '8px',
          height: '8px',
        },
        '::webkit-scrollbar-track': {
          background: 'rgba(0, 0, 0, 0.1)',
        },
        '::webkit-scrollbar-thumb': {
          background: 'rgba(201, 243, 91, 0.25)',
          borderRadius: '4px',
        },
        '::webkit-scrollbar-thumb:hover': {
          background: 'rgba(201, 243, 91, 0.4)',
        },
      });
    }),
  ],
};
