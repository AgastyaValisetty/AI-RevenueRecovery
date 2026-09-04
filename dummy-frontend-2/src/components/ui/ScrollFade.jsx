import React, { useRef, useEffect } from "react";

/**
 * Wrap major content blocks with <ScrollFade> to get a gentle
 * translateY(12px) + opacity fade-in when the element enters the
 * viewport (IntersectionObserver, never window scroll).
 *
 * Staggered children: set --index on each child element and use
 * className="animate-scroll-fade-stagger" on the container instead.
 */
const ScrollFade = ({ children, className = "", ...props }) => {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("animate-scroll-fade");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.08, rootMargin: "0px 0px -24px" }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={className} {...props}>
      {children}
    </div>
  );
};

export default ScrollFade;
