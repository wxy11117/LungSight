import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';
import './workspace-theme.css';
import './case-management.css';
import './workbench.css';
import AppearanceProvider from './appearance-provider';
import { appearanceBootstrap } from './appearance';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000'),
  title: 'LungSight 肺影智析｜肺部 CT 智能辅助分析',
  description: '基于五折深度学习模型的肺部 CT 四分类智能辅助分析平台。',
  openGraph: {
    title: 'LungSight 肺影智析',
    description: '让每一张肺部 CT，更早被看见。',
    images: [{ url: '/og.png', width: 1672, height: 941, alt: 'LungSight 肺影智析品牌预览' }],
    locale: 'zh_CN',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'LungSight 肺影智析',
    description: '让每一张肺部 CT，更早被看见。',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" data-theme="dark" data-accent="classic" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: appearanceBootstrap }} /></head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <AppearanceProvider>{children}</AppearanceProvider>
      </body>
    </html>
  );
}
