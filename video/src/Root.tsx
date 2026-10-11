import React from 'react';
import {Composition} from 'remotion';
import {Demo} from './Demo';
import {FPS, H, TOTAL, W} from './theme';

export const Root: React.FC = () => (
  <Composition id="Demo" component={Demo} durationInFrames={TOTAL} fps={FPS} width={W} height={H} />
);
