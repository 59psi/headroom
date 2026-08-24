import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AnalysisStatus, STAGES } from './AnalysisStatus';
import type { HatRead } from '../../types';

/**
 * The badge sits in a row of pills above the photo on a phone. Its previous
 * form spelled the step out ("Removing background…"), which wrapped onto a
 * second line and shoved the photo down the page — and because the text
 * changed every few seconds, the layout moved while you were reading it. These
 * pin the compact counter that replaced it.
 */
function hat(over: Partial<HatRead>): HatRead {
  return { analysis_status: null, analysis_stage: null, analysis_error: null, ...over } as HatRead;
}

describe('AnalysisStatus', () => {
  it('shows both the step counter and what the step is', () => {
    render(<AnalysisStatus hat={hat({ analysis_status: 'pending', analysis_stage: 'identifying' })} />);

    expect(screen.getByText('2/4')).toBeInTheDocument();
    expect(screen.getByText('Identifying')).toBeInTheDocument();
    // One word, not the full phrase — the long form is what wrapped the pill
    // onto a second line on a phone.
    expect(screen.queryByText(/Identifying the hat/)).not.toBeInTheDocument();
  });

  it('keeps the full step name available to tooltips and screen readers', () => {
    render(<AnalysisStatus hat={hat({ analysis_status: 'pending', analysis_stage: 'pricing' })} />);

    const badge = screen.getByText('3/4').closest('.hr-analysis-status')!;
    expect(badge).toHaveAttribute('title', 'Checking prices — step 3 of 4');
    expect(badge).toHaveAccessibleName('Analyzing: Checking prices, step 3 of 4');
  });

  it('counts every stage the backend publishes', () => {
    // Guards the ordering contract: this array's indexes ARE the numbers shown,
    // so a stage added to the pipeline but not here would silently mis-number
    // every step after it.
    STAGES.forEach((stage, i) => {
      const { unmount } = render(
        <AnalysisStatus hat={hat({ analysis_status: 'pending', analysis_stage: stage })} />,
      );
      expect(screen.getByText(`${i + 1}/${STAGES.length}`)).toBeInTheDocument();
      unmount();
    });
  });

  it('shows 1/4 while queued, before any stage has published', () => {
    render(<AnalysisStatus hat={hat({ analysis_status: 'pending', analysis_stage: null })} />);

    expect(screen.getByText('1/4')).toBeInTheDocument();
    expect(screen.getByText('Analyzing')).toBeInTheDocument();
  });

  it('falls back to 1/4 rather than 0/4 on an unrecognized stage', () => {
    // A newer backend publishing a stage this build doesn't know must not
    // render "0/4", which reads as "nothing is happening".
    render(<AnalysisStatus hat={hat({ analysis_status: 'pending', analysis_stage: 'sizing' })} />);

    expect(screen.getByText('1/4')).toBeInTheDocument();
  });

  it('uses short labels for the statuses that have settled', () => {
    const { rerender } = render(<AnalysisStatus hat={hat({ analysis_status: 'ok' })} />);
    expect(screen.getByText('Analyzed')).toBeInTheDocument();

    rerender(<AnalysisStatus hat={hat({ analysis_status: 'error', analysis_error: 'boom' })} />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Failed').closest('span')).toHaveAttribute('title', 'boom');
  });

  it('renders nothing for a hat that was never analyzed', () => {
    const { container } = render(<AnalysisStatus hat={hat({})} />);
    expect(container).toBeEmptyDOMElement();
  });
});
