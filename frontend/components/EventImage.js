"use client";

import { useEffect, useRef, useState } from "react";
import { CATEGORIES, PENDING_CATEGORY } from "@/lib/reader";
import { Icon } from "@/components/reader";

/** The source photo when we may republish it, otherwise category art - never a broken image. */
export default function EventImage({ src, alt = "", category, className = "", eager = false }) {
  const [failed, setFailed] = useState(false);
  const image = useRef(null);
  // An image that failed before hydration never fires onError; check it once on mount.
  useEffect(() => {
    if (image.current?.complete && image.current.naturalWidth === 0) setFailed(true);
  }, []);
  const key = CATEGORIES[category] ? category : "pending";
  if (src && !failed) {
    return <img ref={image} src={src} alt={alt} loading={eager ? "eager" : "lazy"} decoding="async"
      onError={() => setFailed(true)} className={`object-cover ${className}`} />;
  }
  const meta = CATEGORIES[category] || PENDING_CATEGORY;
  return <div className={`art-${key} relative flex items-center justify-center overflow-hidden text-white/90 ${className}`} aria-hidden="true">
    <svg className="absolute inset-0 h-full w-full opacity-15" aria-hidden="true">
      <defs><pattern id={`dots-${key}`} width="18" height="18" patternUnits="userSpaceOnUse">
        <circle cx="2" cy="2" r="1.4" fill="currentColor" /></pattern></defs>
      <rect width="100%" height="100%" fill={`url(#dots-${key})`} />
    </svg>
    <Icon name={meta.icon} className="relative h-1/3 max-h-20 w-1/3 max-w-20" />
  </div>;
}
