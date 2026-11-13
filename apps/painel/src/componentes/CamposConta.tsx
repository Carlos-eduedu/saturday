import { useEffect, useState } from "react";
import { api, type ContaNova } from "../api";

export const CONTA_VAZIA: ContaNova = {
  banco_codigo: "",
  agencia: "",
  digito_agencia: "",
  numero_conta: "",
  digito_conta: "",
  tipo_conta: "conta_corrente",
};

export type Banco = { codigo: string; nome: string };

// Banco (da lista da Granatech, só os habilitados), agência, conta e tipo.
// Usado em "corrigir conta" (aba Granatech) e na edição da ficha.
export function CamposConta({
  conta,
  mudar,
  aoCarregarBancos,
}: {
  conta: ContaNova;
  mudar: (conta: ContaNova) => void;
  aoCarregarBancos?: (bancos: Banco[]) => void;
}) {
  const [bancos, setBancos] = useState<Banco[] | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    api
      .bancosGranatech()
      .then((lista) => {
        setBancos(lista);
        aoCarregarBancos?.(lista);
      })
      .catch((e: unknown) => setErro(e instanceof Error ? e.message : String(e)));
    // Só na montagem: a lista vem do cache da API.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const campo = (nome: keyof ContaNova) => ({
    value: conta[nome],
    onChange: (e: { target: { value: string } }) => mudar({ ...conta, [nome]: e.target.value }),
  });

  return (
    <>
      {erro && <p className="erro">{erro}</p>}
      <label>
        Banco
        <select {...campo("banco_codigo")} required>
          <option value="">{bancos ? "Escolha" : "Carregando…"}</option>
          {bancos?.map((b) => (
            <option key={b.codigo} value={b.codigo}>
              {b.codigo} · {b.nome}
            </option>
          ))}
        </select>
      </label>
      <label>
        Agência
        <input {...campo("agencia")} inputMode="numeric" pattern="\d{1,6}" required />
      </label>
      <label>
        Dígito da agência
        <input {...campo("digito_agencia")} pattern="[0-9Xx]?" maxLength={1} />
      </label>
      <label>
        Conta
        <input {...campo("numero_conta")} inputMode="numeric" pattern="\d{1,20}" required />
      </label>
      <label>
        Dígito da conta
        <input {...campo("digito_conta")} pattern="[0-9Xx]" maxLength={1} required />
      </label>
      <label>
        Tipo
        <select {...campo("tipo_conta")}>
          <option value="conta_corrente">Conta corrente</option>
          <option value="conta_poupanca">Conta poupança</option>
        </select>
      </label>
    </>
  );
}
