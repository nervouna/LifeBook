import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import styles from "./SignupForm.module.css";

export default function SignupForm() {
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const data = {
      name: form.get("name"),
      email: form.get("email"),
      password: form.get("password"),
    };
    console.log("Signup submitted:", data);
  };

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <h1 className={styles.title}>Create Account</h1>
        <p className={styles.subtitle}>Fill in the form below to get started</p>

        <form onSubmit={handleSubmit}>
          <div className={styles.field}>
            <label htmlFor="name" className={styles.label}>Name</label>
            <Input id="name" name="name" type="text" placeholder="Your full name" required />
          </div>

          <div className={styles.field}>
            <label htmlFor="email" className={styles.label}>Email</label>
            <Input id="email" name="email" type="email" placeholder="you@example.com" required />
          </div>

          <div className={styles.field}>
            <label htmlFor="password" className={styles.label}>Password</label>
            <Input id="password" name="password" type="password" placeholder="Create a password" required minLength={8} />
          </div>

          <div className={styles.footer}>
            <Button type="submit" className={styles.button}>Sign Up</Button>
          </div>
        </form>
      </div>
    </div>
  );
}
