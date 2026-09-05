interface StepNavProps {
  steps: string[];
  current: number;
  onJump: (index: number) => void;
}

export function StepNav({ steps, current, onJump }: StepNavProps) {
  return (
    <ol className="step-nav">
      {steps.map((title, i) => (
        <li key={title} className={i === current ? "active" : i < current ? "done" : ""}>
          <button onClick={() => onJump(i)} type="button">
            {i + 1}. {title}
          </button>
        </li>
      ))}
    </ol>
  );
}
