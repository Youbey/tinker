# Models: what was tried, what was chosen, and why

Everything here was measured on one laptop (Core i5-1245U, 12 threads, Iris Xe, 32 GiB RAM, Fedora Sway 44) by one person. Numbers are small samples. They are meant to explain the choices and to be re-checked with `bench/`, not to rank models in general. Quantizations are the ones named in the install script.

## Chosen

| Role | Model | Evidence |
|---|---|---|
| Decider (System 1) | Decider-2B, Q8_0 GGUF | 9/9 skills and 12/12 multi-step flags on 12 cases; about 1.1 s per request on 8 CPU threads (2.1 s on 4); about 1.1 GB RAM in its container; the image is 1.73 GB because the package depends on PyTorch |
| chat, code, reason, planner | MiniCPM5-2B, Q4_K_M | 2 to 5 s with thinking off; see the notes below |
| writing | Gemma 4 E4B (QAT, UD-Q4_K_XL) | about 9 tok/s; produced real French in a translation test where MiniCPM5 produced nonsense; scored 9/10 and 10/10 on the code bench but took 4 to 5 times as long as MiniCPM5 |
| "think hard" (opt-in) | VibeThinker-3B, Q4_K_M | correct on all questions it finished; 26 to 66 s for 17 x 23, 100 to 172 s for the logic and train questions; writes its reasoning inside the reply and answers in LaTeX, which Tinker strips |
| speech to text | faster-whisper, `base`, with a short vocabulary hint | word error rate 7% to 13% per session (82 words each) |
| text to speech | Piper `en_US-lessac-medium` | works and was judged acceptable for now (TTS will be upgraded later if possible, but it's not the most important in the current phase); not compared with alternatives |

### Notes that cost time to find

- **Reasoning is on by default in MiniCPM5.** A 200-token answer budget was often consumed entirely by hidden thinking, giving an empty reply after about 10 s. Sending `chat_template_kwargs: {"enable_thinking": false}` gave a complete answer in 2.1 s. In "think" mode a harder question hit a 4000-token limit with no answer after 286 s. With thinking off, the same model answered the arithmetic, logic and train-speed questions correctly in 7 to 25 s without any system prompt.
- **A system prompt matters.** Asking "Name three colors." with no system prompt produced refusals in 1 of 9 tries on Vulkan and 3 of 9 on CPU (so it is not a GPU effect); with Tinker's system prompt, 0 of 18.
- **Sampler settings matter for code.** With `top_k 20` and `min_p 0` the code bench gave 8 and 9 of 10; with the server defaults 7 of 10 and 2 of 5, and the replies were sometimes bare code without the requested fence. The `code` skill therefore sets those two options. The samples are small.
- **Threads:** generation speed was flat from 4 to 12 threads (20.6 to 22.3 tok/s) because it is memory-bandwidth bound; extra threads only sped up reading prompts. The installer uses half the CPU threads for llama.cpp and two thirds for the decider.
- **Vulkan on the iGPU** read long prompts about 3 times faster (243 vs 78 tok/s) and left generation unchanged (about 17 vs 18 tok/s).

## Tried and not adopted

| Candidate | Result |
|---|---|
| Laya (decision models) | Not language models. Laya's weights are open, but an external benchmark I found reported it below a majority-class baseline without fine-tuning (not measured here); it is a candidate for fine-tuning on `logs/trace.jsonl` later |
| An LFM2.5-350M prompted as the decider | dropped without testing; Decider is purpose-built and calibrated |
| Sharp-MiniCPM5-2B quants (community, Q4_K_XL and Q6_K_XL) | 8/10 and 7/10 against 8/10 for the stock file under identical settings: no gain |
| Spark-X2.5-4B, community Q6_K_XL | 6/10 on the code bench (twice), failed the simplest task in all four samples, 2.5 times slower than MiniCPM5; writing was slower than Gemma with a grammar slip in French. Its tool-calling claim was not tested |
| Whisper `small` (multilingual) | worse than `base` here (23% vs 18% before the hint) and about 3 times slower |
| Parakeet-TDT 0.6B v3 via onnx-asr, int8 | 14.6% to 20.7% word error rate; returned an empty transcript for one whole sentence; the full-precision model was no better (24% vs 20.5%) and 2.3 GB |
| OmniVoice (text to speech, 0.6B) | not installed. A third-party server reports a CPU real-time factor of about 4.9 (roughly five times slower than real time), too slow for spoken replies |

## Speech findings

- Trimming 0.25 s from each end of a clip helped Parakeet but not Whisper, and could cut the first word, so Tinker does not trim.
- The vocabulary hint helped Whisper with the words in it (about 2 words of 82 in one session), but the hint list contained words from the test sentences, so that is an upper bound.
- An earphone microphone gave peaks of 1% to 27%; the laptop's own microphone gave 40% to 100%. Clipping did not wreck accuracy, but `tinker on` lowers the input level and boosts quiet clips automatically.
