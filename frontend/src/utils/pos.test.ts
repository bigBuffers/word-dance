import { describe, expect, it } from 'vitest';
import { formatPos, isPosRatio } from './pos';

describe('formatPos', () => {
  it('renders an ECDICT pos ratio as readable shares, dominant class first', () => {
    expect(formatPos('n:4/v:96')).toBe('v. 96% · n. 4%');
    expect(formatPos('v:11/n:89')).toBe('n. 89% · v. 11%');
    expect(formatPos('a:99/t:1')).toBe('art. 99%'); // shares below 2 % are dropped
    expect(formatPos('n:100')).toBe('n. 100%');
    expect(formatPos('j:50/r:50')).toBe('adj. 50% · adv. 50%');
    expect(formatPos('q:100')).toBe('q. 100%'); // unknown tag letters still render
  });

  it('passes dictionary labels through and yields null for empty input', () => {
    expect(formatPos('v./n.')).toBe('v./n.');
    expect(formatPos('abbr.')).toBe('abbr.');
    expect(formatPos(' adj. ')).toBe('adj.');
    expect(formatPos(null)).toBeNull();
    expect(formatPos(undefined)).toBeNull();
    expect(formatPos('   ')).toBeNull();
    expect(isPosRatio('n:4/v:96')).toBe(true);
    expect(isPosRatio('v./n.')).toBe(false);
  });
});
