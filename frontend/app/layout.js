import "./globals.css";

export const metadata = { title: "News Intelligence", description: "Persian analyst feed" };

export default function RootLayout({ children }) {
  return <html lang="en"><body>{children}</body></html>;
}
