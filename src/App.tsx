export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 flex items-center justify-center p-8">
      <div className="max-w-2xl text-center space-y-6">
        <h1 className="text-4xl font-bold text-white">ReputationOracle</h1>
        <p className="text-lg text-slate-400">
          A GenLayer Intelligent Contract Primitive
        </p>
        <div className="space-y-2 text-sm text-slate-500">
          <p>
            Contract:{" "}
            <code className="text-amber-400 font-mono text-xs">
              0x855C4307De29B4895271fD7Da24cd039EDD19151
            </code>
          </p>
          <p>Network: StudioNet (chain id 61999)</p>
        </div>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <a
            href="https://explorer-studio.genlayer.com/address/0x855C4307De29B4895271fD7Da24cd039EDD19151"
            target="_blank"
            rel="noopener noreferrer"
            className="px-5 py-2.5 rounded-lg bg-slate-800 text-slate-300 text-sm hover:bg-slate-700 border border-slate-700"
          >
            Explorer ↗
          </a>
          <a
            href="https://studio.genlayer.com/?import-contract=0x855C4307De29B4895271fD7Da24cd039EDD19151"
            target="_blank"
            rel="noopener noreferrer"
            className="px-5 py-2.5 rounded-lg bg-amber-500/20 text-amber-400 text-sm hover:bg-amber-500/30 border border-amber-500/30"
          >
            GenLayer Studio ↗
          </a>
        </div>
      </div>
    </div>
  );
}
