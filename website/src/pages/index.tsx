import Layout from '@theme/Layout';
import Homepage from '../components/Homepage';

export default function Home(): React.JSX.Element {
  return (
    <Layout
      title="Local-first agent runtime"
      description="Fabric keeps models, memory, skills, approvals, and sessions together across desktop, terminal, web, messaging, and IDE workflows."
    >
      <Homepage />
    </Layout>
  );
}
