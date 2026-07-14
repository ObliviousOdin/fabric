import Layout from '@theme/Layout';
import Homepage from '../components/Homepage';

export default function Home(): React.JSX.Element {
  return (
    <Layout
      title="Local-first multi-agent runtime"
      description="Fabric connects conversations, agents, memory, automations, and runtime controls across desktop, terminal, web, messaging, and IDE workflows."
    >
      <Homepage />
    </Layout>
  );
}
