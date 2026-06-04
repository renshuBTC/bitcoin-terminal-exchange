import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        // BTX design tokens — match assets/btx.css.
        bg: '#000',
        fg: '#d4d4d4',
        'fg-bright': '#fff',
        muted: '#888',
        dim: '#666',
        border: '#2a2a2a',
        'border-soft': '#1f1f1f',
        hover: '#1a1a1a',
        panel: '#0d0d0d',
        'line-strong': '#555',
        orange: '#ff8c00',
        'orange-bright': '#ffaa33',
        red: '#f0616d',
        green: '#26a69a',
      },
      fontFamily: {
        mono: ['Source Code Pro', 'Consolas', 'Menlo', 'monospace'],
        display: ['Roboto Condensed', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};

export default config;
