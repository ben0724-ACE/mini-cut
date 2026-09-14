import { expect,it } from 'vitest';
import { render,screen } from '@testing-library/react';
import { ModelUsage } from './ModelUsage';
it('缺少用量和价格时显示未知，不误算为零',()=>{
  render(<ModelUsage requests={[{model:'test',reused:false,usage:{prompt_tokens:null,completion_tokens:10,prompt_cache_hit_tokens:null,prompt_cache_miss_tokens:null},estimated_cost_usd:null}]} />);
  for (const label of ['缓存命中 Token', '缓存未命中 Token', '输入 Token']) {
    expect(screen.getByText(label).parentElement).toHaveTextContent('未知');
  }
  expect(screen.getByText('未知（未配置价格或用量）')).toBeInTheDocument();
});
