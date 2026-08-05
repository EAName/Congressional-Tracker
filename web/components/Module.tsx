import type { ReactNode } from "react";

export default function Module({
  title,
  kicker,
  span = 12,
  children,
  action,
}: {
  title: string;
  kicker?: string;
  span?: 4 | 6 | 8 | 12;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className={`module span-${span}`}>
      <header className="module-head">
        <div>
          <h2 className="module-title">{title}</h2>
          {kicker ? <p className="module-kicker">{kicker}</p> : null}
        </div>
        {action}
      </header>
      <div className="module-body">{children}</div>
    </section>
  );
}
