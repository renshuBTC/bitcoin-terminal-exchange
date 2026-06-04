import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Bitcoin orange + neutral palette.
        'btc-orange': '#f7931a',
        'panel': '#0f1218',
        'panel-2': '#161b24',
        'border-strong': '#2a3140',
        'fg-1': '#e7ebf3',
        'fg-2': '#9aa3b2',
        'green-up': '#26a69a',
        'red-down': '#ef5350',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'monospace'],
      },
    },
  },
  plugins: [],
};

export default config;
